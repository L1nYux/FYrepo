/* The account menu is shared; usage charts remain an API-page feature. */
(() => {
  document.querySelectorAll('[data-usage-popup]').forEach(root => {
    const account = root.closest('details'); if (!account) return;
    window.zhiyuRuntime.mount('account-usage', root, scope => {
      const lookup = scope.latest();
      const week = root.querySelector('[data-usage-period="week"]');
      root.querySelector('[data-usage-period="month"]').hidden = true;
      scope.on(account, 'toggle', async () => {
        if (!account.open) { lookup.cancel(); return; }
        week.querySelector('span').textContent = '正在加载…';
        week.querySelector('progress').hidden = true; week.querySelector('small').textContent = '';
        try {
          const data = await lookup.run(signal => window.zhiyuRuntime.query(root.dataset.usagePopup, {signal}));
          if (!account.open) return;
          const period = data.budget.member_week;
          week.querySelector('span').textContent = period.limit === null ? '未设上限' : Math.round(period.remaining_percent) + '% 剩余';
          week.querySelector('progress').hidden = period.limit === null;
          week.querySelector('progress').value = period.used_percent;
          const points = period.limit === null ? period.spent_points ?? Number(period.spent) * 100 : period.remaining_points ?? Number(period.remaining) * 100;
          week.querySelector('small').textContent = (period.limit === null ? '已用 ' : '基础剩余 ') + Number(points).toLocaleString('zh-CN', {maximumFractionDigits:1}) + ' 点 · 额外 ' + Number(data.budget.extra?.remaining_points || 0).toLocaleString('zh-CN', {maximumFractionDigits:1}) + ' 点';
        } catch (error) {
          if (error.name !== 'AbortError' && scope.alive() && account.open) week.querySelector('span').textContent = '暂不可用';
        }
      });
    });
  });
})();
