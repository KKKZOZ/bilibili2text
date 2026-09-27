// Empty by default so local Vite/Nginx deployments keep using their /api proxy.
export const apiUrl = (
  url,
  baseUrl = import.meta.env.VITE_API_BASE_URL || ''
) => {
  if (typeof url !== 'string' || !url.startsWith('/api/')) return url
  return `${baseUrl.trim().replace(/\/+$/, '')}${url}`
}
