// Обновляем только публичный счёт. Все изменения данных выполняются POST-формами.
const scoreboard = document.querySelector('[data-match-state]');
if (scoreboard) {
  const refresh = async () => {
    if (document.hidden) return;
    try {
      const response = await fetch(scoreboard.dataset.matchState, {headers: {'Accept':'application/json'}, cache:'no-store'});
      if (!response.ok) return;
      const state = await response.json();
      const a = scoreboard.querySelector('[data-score-a]');
      const b = scoreboard.querySelector('[data-score-b]');
      const status = scoreboard.querySelector('[data-live-status]');
      if (a) a.textContent = state.score_a ?? '—';
      if (b) b.textContent = state.score_b ?? '—';
      if (status) { status.textContent = state.status_label; status.className = `badge ${state.status}`; }
    } catch { /* Текущий результат остаётся на экране при временной потере сети. */ }
  };
  window.setInterval(refresh, 20000);
}

// Read-only sections update together so the bracket and table remain consistent.
if (document.querySelector('[data-refresh-tournament]')) {
  window.setInterval(async () => {
    if (document.hidden || document.activeElement?.closest('.table-scroll, .bracket-scroll')) return;
    try {
      const response = await fetch(window.location.pathname, {cache:'no-store'});
      if (!response.ok) return;
      const fresh = new DOMParser().parseFromString(await response.text(), 'text/html');
      for (const id of ['bracket', 'schedule', 'standings']) {
        const current = document.getElementById(id);
        const updated = fresh.getElementById(id);
        if (current && updated) current.replaceChildren(...updated.childNodes);
      }
    } catch { /* Сохранённые на экране данные остаются доступными без сети. */ }
  }, 20000);
}
