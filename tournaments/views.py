from collections import defaultdict
import calendar
from datetime import date as calendar_date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from urllib.parse import urlencode
from django.views.decorators.http import require_POST, require_http_methods

from . import services
from .match_operations import change_pairing
from .models import Match, MatchConfirmation, Stream, Team, TeamMember, Tournament, TournamentTeam, User
from .tournament_forms import MatchEditForm, PairingForm, StreamForm, TournamentForm


def public_tournaments():
    return Tournament.objects.exclude(status=Tournament.Status.DRAFT).annotate(
        team_count=Count('entries', filter=Q(entries__status='approved')),
    ).select_related('organizer').order_by('edition', 'pk')


def visible_tournament(request, slug):
    tournament = get_object_or_404(Tournament.objects.select_related('organizer'), slug=slug)
    if tournament.status == Tournament.Status.DRAFT and not services.can_manage_tournament(request.user, tournament):
        raise Http404('Турнир не найден')
    return tournament


def manager_tournament(request, slug):
    tournament = get_object_or_404(Tournament, slug=slug)
    if not services.can_manage_tournament(request.user, tournament):
        raise PermissionDenied('Управлять можно только своим турниром.')
    return tournament


def visible_match(request, pk):
    match = get_object_or_404(Match.objects.select_related('tournament__organizer', 'team_a__captain', 'team_b__captain'), pk=pk)
    if match.tournament.status == Tournament.Status.DRAFT and not services.can_manage_tournament(request.user, match.tournament):
        raise Http404('Матч не найден')
    return match


def home(request):
    matches = Match.objects.exclude(tournament__status='draft').filter(is_bye=False).select_related('tournament', 'team_a', 'team_b')
    archive_matches = matches.exclude(source_url='').filter(status='finished').order_by('-scheduled_at', '-round', 'position')
    return render(request, 'home.html', {
        'featured': public_tournaments().first(),
        'featured_match': archive_matches.first() or matches.filter(status='live').first() or matches.order_by('-scheduled_at').first(),
        'archive_matches': archive_matches[:6],
        'tournaments': public_tournaments()[:6],
        'upcoming_matches': matches.filter(status='planned').order_by('scheduled_at', 'pk')[:5],
        'live_matches': matches.filter(status='live')[:4],
        'streams': Stream.objects.exclude(match__tournament__status='draft').select_related('match__tournament', 'match__team_a', 'match__team_b').order_by('-match__scheduled_at', '-pk')[:3],
        'counts': {'tournaments': public_tournaments().count(), 'teams': Team.objects.count(), 'matches': matches.filter(status='finished').count()},
    })


def tournament_list(request):
    query = request.GET.get('q', '').strip()[:120]
    game, status = request.GET.get('game', ''), request.GET.get('status', '')
    tournaments = public_tournaments()
    if query:
        tournaments = tournaments.filter(Q(name__icontains=query) | Q(subtitle__icontains=query))
    if game:
        tournaments = tournaments.filter(game=game)
    if status:
        tournaments = tournaments.filter(status=status)
    return render(request, 'tournament_list.html', {
        'tournaments': tournaments, 'query': query, 'game': game, 'status': status,
        'game_choices': Tournament.Game.choices,
        'status_choices': [(key, label) for key, label in Tournament.Status.choices if key != 'draft'],
    })


def tournament_detail(request, slug):
    tournament = visible_tournament(request, slug)
    matches = list(tournament.matches.select_related('team_a', 'team_b'))
    grouped = defaultdict(list)
    for match in matches:
        grouped[match.round].append(match)
    last = max(grouped, default=0)
    final = tournament.format == 'single' and len(grouped.get(last, [])) == 1
    rounds = []
    for number, rows in sorted(grouped.items()):
        title = f'Тур {number}' if tournament.format == 'round_robin' else 'Финал' if final and number == last else 'Полуфиналы' if final and number == last - 1 else f'Раунд {number}'
        rounds.append({'number': number, 'title': title, 'matches': rows})
    entries = tournament.entries.filter(status='approved').select_related('team__captain').annotate(member_count=Count('team__memberships', filter=Q(team__memberships__status='active')))
    eligible = Team.objects.none()
    own_entries = TournamentTeam.objects.none()
    if request.user.is_authenticated:
        eligible = Team.objects.filter(captain=request.user).exclude(entries__tournament=tournament)
        own_entries = tournament.entries.filter(team__captain=request.user).select_related('team')
    return render(request, 'tournament_detail.html', {
        'tournament': tournament, 'entries': entries, 'rounds': rounds, 'matches': matches,
        'standings': services.standings(tournament), 'can_manage': services.can_manage_tournament(request.user, tournament),
        'eligible_teams': eligible, 'own_entries': own_entries,
        'registration_available': tournament.status == 'soon' and tournament.registration_open and not matches,
    })


def form_response(request, form, title, cancel_url='/', submit_label='Сохранить', description=''):
    return render(request, 'form.html', {'form': form, 'title': title, 'cancel_url': cancel_url, 'submit_label': submit_label, 'description': description})


@login_required
@require_http_methods(['GET', 'POST'])
def tournament_create(request):
    if request.user.role != User.Role.ORGANIZER and not request.user.is_superuser:
        messages.info(request, 'Включите режим организатора в личном кабинете.')
        return redirect('dashboard')
    form = TournamentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        tournament = form.save(commit=False)
        tournament.organizer = request.user
        tournament.save()
        messages.success(request, 'Турнир создан. Проверьте настройки и откройте регистрацию.')
        return redirect('tournament_manage', slug=tournament.slug)
    return form_response(request, form, 'Создать турнир', reverse('dashboard'), 'Создать')


@login_required
@require_http_methods(['GET', 'POST'])
def tournament_edit(request, slug):
    tournament = manager_tournament(request, slug)
    with transaction.atomic():
        tournament = Tournament.objects.select_for_update().get(pk=tournament.pk)
        form = TournamentForm(request.POST or None, instance=tournament)
        if request.method == 'POST' and form.is_valid():
            form.save()
            messages.success(request, 'Настройки турнира сохранены.')
            return redirect('tournament_manage', slug=slug)
    return form_response(request, form, 'Настройки турнира', reverse('tournament_manage', args=[slug]))


@login_required
def tournament_manage(request, slug):
    tournament = manager_tournament(request, slug)
    return render(request, 'tournament_manage.html', {
        'tournament': tournament, 'entries': tournament.entries.select_related('team__captain'),
        'matches': tournament.matches.select_related('team_a', 'team_b'), 'can_manage': True,
    })


@login_required
@require_POST
def tournament_action(request, slug):
    tournament = manager_tournament(request, slug)
    try:
        action = request.POST.get('action')
        if action == 'generate':
            services.generate_bracket(tournament, request.user, request.POST.get('seeding', 'random'))
            messages.success(request, 'Сетка сформирована. Можно назначить время матчей и запустить турнир.')
        elif action == 'start':
            services.start_tournament(tournament, request.user)
            messages.success(request, 'Турнир начался.')
        elif action in ('publish', 'registration'):
            with transaction.atomic():
                tournament = Tournament.objects.select_for_update().get(pk=tournament.pk)
                if tournament.status not in ('draft', 'soon'):
                    raise ValidationError('Турнир уже начался.')
                if action == 'publish':
                    tournament.status = Tournament.Status.SOON
                    tournament.registration_open = not tournament.matches.exists()
                else:
                    if tournament.matches.exists():
                        raise ValidationError('Регистрация доступна только до формирования сетки.')
                    tournament.registration_open = not tournament.registration_open
                tournament.save(update_fields=['status', 'registration_open'])
                messages.success(request, 'Турнир опубликован.' if action == 'publish' else 'Настройки регистрации обновлены.')
        else:
            raise ValidationError('Неизвестное действие.')
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    return redirect('tournament_manage', slug=slug)


@login_required
@require_POST
def tournament_apply(request, slug):
    tournament = visible_tournament(request, slug)
    try:
        with transaction.atomic():
            tournament = Tournament.objects.select_for_update().get(pk=tournament.pk)
            if tournament.status != 'soon' or not tournament.registration_open or tournament.matches.exists():
                raise ValidationError('Регистрация на турнир закрыта.')
            team_id = request.POST.get('team_id', '')
            if not team_id.isdecimal():
                raise ValidationError('Выберите свою команду.')
            team = get_object_or_404(Team, pk=team_id, captain=request.user)
            entry, created = TournamentTeam.objects.get_or_create(tournament=tournament, team=team)
            if request.POST.get('action') == 'withdraw':
                if created:
                    raise ValidationError('Заявка не найдена.')
                entry.status, entry.seed = 'rejected', None
                entry.save(update_fields=['status', 'seed'])
                messages.success(request, 'Заявка отозвана.')
            elif created:
                messages.success(request, 'Заявка отправлена организатору.')
            else:
                raise ValidationError('Команда уже подавала заявку на этот турнир.')
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    return redirect('tournament_detail', slug=slug)


@login_required
@require_POST
def entry_action(request, slug, pk):
    tournament = manager_tournament(request, slug)
    entry = get_object_or_404(TournamentTeam.objects.select_related('tournament'), pk=pk, tournament=tournament)
    try:
        seed = request.POST.get('seed', '').strip()
        if seed and not seed.isdecimal():
            raise ValidationError('Номер посева должен быть положительным числом.')
        action = request.POST.get('action')
        if action not in ('approve', 'reject', 'seed'):
            raise ValidationError('Неизвестное действие.')
        services.decide_entry(entry, request.user, action != 'reject', int(seed) if seed else None)
        messages.success(request, 'Заявка обновлена.')
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    return redirect('tournament_manage', slug=slug)


def match_detail(request, pk):
    match = visible_match(request, pk)
    roster_ids = {pk for ids in match.participants_snapshot.values() for pk in ids}
    roster_players = {player.pk: player for player in User.objects.filter(pk__in=roster_ids)}
    revision = match.result_logs.order_by('-pk').values_list('pk', flat=True).first() or 0
    captain_teams = [team for team in (match.team_a, match.team_b) if team and request.user.is_authenticated and team.captain_id == request.user.pk]
    return render(request, 'match_detail.html', {
        'match': match, 'can_manage': services.can_manage_tournament(request.user, match.tournament),
        'streams': [{'stream': stream, 'embed_url': stream.embed_url(request.get_host().split(':')[0])} for stream in match.streams.all()],
        'history': match.result_logs.select_related('changed_by'),
        'confirmations': match.confirmations.filter(result_revision=revision).select_related('team', 'confirmed_by'),
        'can_confirm': match.status == 'finished' and not match.is_bye and not match.source_url,
        'captain_teams': captain_teams,
        'result_revision': revision,
        'rosters': [
            {'team': team, 'players': [roster_players[pk] for pk in match.participants_snapshot.get(side, []) if pk in roster_players]}
            for side, team in (('a', match.team_a), ('b', match.team_b))
        ] if roster_ids else [],
    })


@login_required
@require_http_methods(['GET', 'POST'])
def match_edit(request, pk):
    match = visible_match(request, pk)
    if not services.can_manage_tournament(request.user, match.tournament):
        raise PermissionDenied
    form = MatchEditForm(request.POST or None, match=match)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                data = form.cleaned_data
                if data['scheduled_at'] != match.scheduled_at:
                    match = services.update_schedule(match, request.user, data['scheduled_at'])
                if (data['score_a'], data['score_b'], data['status']) != (match.score_a, match.score_b, match.status):
                    services.update_result(match, request.user, data['score_a'], data['score_b'], data['status'])
            messages.success(request, 'Матч обновлён.')
            return redirect('match_detail', pk=pk)
        except ValidationError as error:
            form.add_error(None, error)
    return form_response(request, form, 'Расписание и результат матча', match.get_absolute_url())


@login_required
@require_http_methods(['GET', 'POST'])
def match_pair_edit(request, pk):
    match = visible_match(request, pk)
    if not services.can_manage_tournament(request.user, match.tournament):
        raise PermissionDenied
    if match.tournament.status not in ('draft', 'soon') or match.round != 1 or match.tournament.format != 'single':
        raise PermissionDenied('Пары редактируются только до старта турнира.')
    form = PairingForm(request.POST or None, match=match)
    if request.method == 'POST' and form.is_valid():
        try:
            change_pairing(match, request.user, **form.cleaned_data)
            messages.success(request, 'Соперники изменены.')
            return redirect('tournament_manage', slug=match.tournament.slug)
        except ValidationError as error:
            form.add_error(None, error)
    return form_response(request, form, 'Изменить пару', reverse('tournament_manage', args=[match.tournament.slug]))


@login_required
@require_POST
def match_confirm(request, pk):
    match = visible_match(request, pk)
    with transaction.atomic():
        Tournament.objects.select_for_update().get(pk=match.tournament_id)
        match = Match.objects.select_for_update().get(pk=pk)
        team_id = request.POST.get('team_id', '')
        if not team_id.isdecimal():
            raise PermissionDenied
        team = get_object_or_404(Team, pk=team_id, captain=request.user)
        if team.pk not in (match.team_a_id, match.team_b_id):
            raise PermissionDenied
        if match.status != 'finished' or match.is_bye or match.score_a is None:
            messages.error(request, 'Подтверждение доступно после завершения матча.')
        else:
            revision = match.result_logs.order_by('-pk').values_list('pk', flat=True).first() or 0
            if request.POST.get('result_revision') != str(revision):
                messages.error(request, 'Результат изменился. Проверьте актуальный счёт и подтвердите его ещё раз.')
                return redirect('match_detail', pk=pk)
            MatchConfirmation.objects.update_or_create(match=match, team=team, defaults={
                'confirmed_by': request.user, 'result_revision': revision,
                'score_a': match.score_a, 'score_b': match.score_b, 'confirmed_at': timezone.now(),
            })
            messages.success(request, 'Результат подтверждён.')
    return redirect('match_detail', pk=pk)


@login_required
@require_http_methods(['GET', 'POST'])
def match_stream_add(request, pk):
    match = visible_match(request, pk)
    if not services.can_manage_tournament(request.user, match.tournament):
        raise PermissionDenied
    form = StreamForm(request.POST or None, instance=Stream(match=match))
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Трансляция добавлена.')
        return redirect('match_detail', pk=pk)
    return form_response(request, form, 'Добавить трансляцию', match.get_absolute_url())


@login_required
@require_http_methods(['GET', 'POST'])
def stream_edit(request, pk):
    stream = get_object_or_404(Stream.objects.select_related('match__tournament'), pk=pk)
    if not services.can_manage_tournament(request.user, stream.match.tournament):
        raise PermissionDenied
    form = StreamForm(request.POST or None, instance=stream)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Трансляция обновлена.')
        return redirect('match_detail', pk=stream.match_id)
    return form_response(request, form, 'Изменить трансляцию', stream.match.get_absolute_url())


def match_list(request):
    matches = Match.objects.exclude(tournament__status='draft').filter(is_bye=False).select_related('team_a', 'team_b', 'tournament')
    query = request.GET.get('q', '').strip()[:120]
    status = request.GET.get('status', '')
    tournament_id, team_id = request.GET.get('tournament', ''), request.GET.get('team', '')
    date = request.GET.get('date', '')
    mine = request.GET.get('mine') == '1'
    if query:
        matches = matches.filter(Q(team_a__name__icontains=query) | Q(team_b__name__icontains=query) | Q(tournament__name__icontains=query))
    if status:
        matches = matches.filter(status=status)
    if tournament_id.isdecimal():
        matches = matches.filter(tournament_id=tournament_id)
    if team_id.isdecimal():
        matches = matches.filter(Q(team_a_id=team_id) | Q(team_b_id=team_id))
    if date:
        try:
            parsed = parse_date(date)
        except ValueError:
            parsed = None
        if parsed:
            matches = matches.filter(scheduled_at__date=parsed)
    if mine:
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?{urlencode({'next': request.get_full_path()})}")
        matches = matches.filter(pk__in=services.player_matches(request.user).values('pk'))
    return render(request, 'match_list.html', {
        'matches': matches.order_by('-scheduled_at', '-pk'), 'query': query, 'status': status,
        'tournament_id': tournament_id, 'team_id': team_id, 'date': date, 'mine': mine,
        'tournaments': public_tournaments(), 'teams': Team.objects.all(), 'status_choices': Match.Status.choices,
    })


def live_streams(request):
    return render(request, 'live_streams.html', {'streams': Stream.objects.exclude(match__tournament__status='draft').select_related('match__tournament', 'match__team_a', 'match__team_b').order_by('status', '-pk')})


def match_state(request, pk):
    match = visible_match(request, pk)
    response = JsonResponse({'score_a': match.score_a, 'score_b': match.score_b, 'status': match.status, 'status_label': match.get_status_display()})
    response['Cache-Control'] = 'no-store'
    return response


def match_calendar(request):
    current = timezone.localdate()
    try:
        year, month = map(int, request.GET.get('month', current.strftime('%Y-%m')).split('-'))
        if not 2020 <= year <= 2100 or not 1 <= month <= 12:
            raise ValueError
        selected = calendar_date(year, month, 1)
    except (ValueError, TypeError):
        selected = current.replace(day=1)
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(selected.year, selected.month)
    matches = Match.objects.filter(is_bye=False, scheduled_at__date__range=(weeks[0][0], weeks[-1][-1])).exclude(tournament__status='draft').select_related('team_a', 'team_b', 'tournament')
    mine = request.GET.get('mine') == '1'
    if mine:
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?{urlencode({'next': request.get_full_path()})}")
        matches = matches.filter(pk__in=services.player_matches(request.user).values('pk'))
    grouped = defaultdict(list)
    for match in matches.order_by('scheduled_at'):
        grouped[timezone.localtime(match.scheduled_at).date()].append(match)
    cells = [[{'date': day, 'in_month': day.month == selected.month, 'today': day == current, 'matches': grouped[day]} for day in week] for week in weeks]
    previous = selected.replace(year=selected.year - 1, month=12) if selected.month == 1 else selected.replace(month=selected.month - 1)
    following = selected.replace(year=selected.year + 1, month=1) if selected.month == 12 else selected.replace(month=selected.month + 1)
    return render(request, 'calendar.html', {'weeks': cells, 'selected': selected, 'previous': previous.strftime('%Y-%m'), 'following': following.strftime('%Y-%m'), 'mine': mine})


def previews(request, page=None):
    routes = {'register': 'register', 'login': 'login', 'player': 'dashboard', 'team': 'team_list', 'organizer': 'dashboard'}
    if page is not None and page not in routes:
        raise Http404('Страница не найдена')
    return redirect(routes.get(page, 'home'))
