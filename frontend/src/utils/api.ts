export async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { error?: string; code?: string } | null
    if (response.status === 401 && payload?.code === 'dashboard_access_required') {
      window.dispatchEvent(new Event('dashboard-access-required'))
    }
    throw new Error(payload?.error || `请求失败 ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function formatError(error: unknown): string {
  if (error instanceof Error) {
    return error.message
  }
  return '请求失败，请稍后重试'
}
