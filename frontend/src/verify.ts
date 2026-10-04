import type { Assignment } from './types'

function hex(bytes: Uint8Array) { return [...bytes].map(byte => byte.toString(16).padStart(2, '0')).join('') }
function unhex(value: string) { return new Uint8Array(value.match(/.{2}/g)?.map(part => parseInt(part, 16)) || []) }

export async function verifyAssignment(assignment: Assignment): Promise<{ commitment: boolean; selection: boolean }> {
  if (!assignment.seed) return { commitment: false, selection: false }
  const seed = unhex(assignment.seed)
  const commitment = hex(new Uint8Array(await crypto.subtle.digest('SHA-256', seed))) === assignment.commitment
  const key = await crypto.subtle.importKey('raw', seed, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  const total = assignment.eligible.reduce((sum, item) => sum + item.weight, 0)
  if (total <= 0 || assignment.algorithm !== 'hmac-sha256-rejection-v1') return { commitment, selection: false }
  const space = 1n << 256n
  const limit = space - space % BigInt(total)
  for (let counter = 0; counter < 1000; counter++) {
    const message = JSON.stringify({ case_id: assignment.case_id, candidates: assignment.eligible, event_number: assignment.event_number, counter })
    const digest = new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(message)))
    const number = BigInt(`0x${hex(digest)}`)
    if (number >= limit) continue
    let pick = Number(number % BigInt(total))
    for (const candidate of assignment.eligible) {
      if (pick < candidate.weight) return { commitment, selection: candidate.id === assignment.selected_inspector_id }
      pick -= candidate.weight
    }
  }
  return { commitment, selection: false }
}
