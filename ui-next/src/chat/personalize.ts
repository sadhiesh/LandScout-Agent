/**
 * Conversational, name-aware copy for the moments that warrant it —
 * greeting, milestone delivery, memory short-circuit callback, and errors.
 * "Moderate" cadence (see memory/ui_wireframe_decisions.md): deliberately
 * NOT used in the live narration bubble or on every turn, so the name
 * lands like a human advisor would use it rather than a template.
 */

export function greeting(name: string, returning: boolean): string {
  return returning
    ? `Welcome back, ${name}! What kind of land are you looking for?`
    : `Hello, ${name}! Tell me about the land you want — acreage, location, budget, and use.`
}

export function milestoneLead(name: string | null, count: number): string {
  if (!name) return count === 1 ? 'Found 1 strong match.' : `Found ${count} strong matches.`
  return count === 1 ? `${name}, I found 1 strong match.` : `${name}, I found ${count} strong matches.`
}

export function memoryCallbackLead(name: string | null): string {
  return name
    ? `Since you already asked about this, ${name}, here's what I found last time.`
    : "Since you already asked about this, here's what I found last time."
}

export function errorLead(name: string | null): string {
  return name ? `Sorry ${name}, something went wrong on my end.` : 'Sorry, something went wrong on my end.'
}
