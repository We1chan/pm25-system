export function verificationHref(cycleId, stationId, target, back) {
  const query = new URLSearchParams({ cycle_id: cycleId, station_id: stationId })
  if (target) query.set('target', target)
  if (back) query.set('back', back)
  return `#online?${query}`
}

export function verificationRecordsHref(forecast, back) {
  const query = new URLSearchParams({ view: 'records', cycle_id: forecast.cycle_id })
  if (back) query.set('back', back)
  const points = forecast.points || []
  if (points.length) {
    query.set('start', points[0].target.slice(0, 10))
    query.set('end', points.at(-1).target.slice(0, 10))
  }
  return `#online?${query}`
}
