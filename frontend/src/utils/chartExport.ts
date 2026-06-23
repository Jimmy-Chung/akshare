import { toPng } from 'html-to-image'

export function normalizeChartId(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

export function downloadChartImage(dataUrl: string, filename: string) {
  const link = document.createElement('a')
  link.href = dataUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
}

export function downloadCanvasImage(canvas: HTMLCanvasElement, filename: string) {
  canvas.toBlob((blob) => {
    if (!blob) return
    const objectUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 30_000)
  }, 'image/png')
}

export async function exportChartElement(chartId: string, filename: string) {
  const element = document.querySelector<HTMLElement>(`[data-chart-id="${chartId}"]`)
  if (!element) {
    throw new Error(`找不到图表：${chartId}`)
  }
  const dataUrl = await toPng(element, {
    backgroundColor: '#ffffff',
    cacheBust: true,
    pixelRatio: element.offsetWidth > 1200 ? 1 : 2,
    skipFonts: true,
  })
  downloadChartImage(dataUrl, filename)
}
