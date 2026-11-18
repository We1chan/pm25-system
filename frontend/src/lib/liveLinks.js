export function verificationHref(cycleId, stationId, target) {
  const query = new URLSearchParams({ cycle_id: cycleId, station_id: stationId })
  if (target) query.set('target', target)
  return `#online?${query}`
}
