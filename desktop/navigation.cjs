// Match more specific settings routes before their query-free parent route.
function resolveSettingsPage(location, routes, settingsPages) {
  if(location.pathname.startsWith('/account/forgot-code/') || location.pathname==='/account/forgot/')return 'security';
  if (settingsPages.has('recycle') && location.pathname.startsWith(routes.recycle)) return 'recycle';
  return Object.entries(routes)
    .filter(([name]) => settingsPages.has(name))
    .map(([name, route]) => [name, new URL(route, 'http://local.invalid')])
    .filter(([, route]) => route.pathname === location.pathname)
    .sort((a, b) => b[1].searchParams.size - a[1].searchParams.size)
    .find(([, route]) => [...route.searchParams].every(([key, value]) => location.searchParams.get(key) === value))?.[0];
}
module.exports = { resolveSettingsPage };
