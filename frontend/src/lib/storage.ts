/**
 * localStorage access that never throws. Storage can be unavailable or full
 * (private browsing, blocked site data, quota), and preferences are a
 * nice-to-have — so failures degrade to "not persisted" instead of crashing.
 */

export function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

export function writeStorage(key: string, value: string): boolean {
  try {
    window.localStorage.setItem(key, value)
    return true
  } catch {
    return false
  }
}

export function removeStorage(key: string): void {
  try {
    window.localStorage.removeItem(key)
  } catch {
    // Ignore: nothing to clean up if storage is unavailable.
  }
}
