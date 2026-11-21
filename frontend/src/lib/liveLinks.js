export function verificationHref(cycleId, stationId, target) {
  const query = new URLSearchParams({ cycle_id: cycleId, station_id: stationId })
  if (target) query.set('target', target)
  return `#online?${query}`
}

export function verificationRecordsHref(forecast) {
  const query = new URLSearchParams({ view: 'records', cycle_id: forecast.cycle_id })
  const points = forecast.points || []
  if (points.length) {
    query.set('start', points[0].target.slice(0, 10))
    query.set('end', points.at(-1).target.slice(0, 10))
  }
  return `#online?${query}`
}
