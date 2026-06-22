export async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    throw new Error(`请求失败 ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function formatError(error: unknown): string {
  if (error instanceof Error) {
    return error.message
  }
  return '请求失败，请稍后重试'
}
