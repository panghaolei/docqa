import axios from 'axios'

const TOKEN_KEY = 'docqa_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(t) {
  localStorage.setItem(TOKEN_KEY, t)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

const http = axios.create({
  baseURL: '/api',
  timeout: 60000
})

http.interceptors.request.use(config => {
  const token = getToken()
  if (token) {
    config.headers['Authorization'] = 'Bearer ' + token
  }
  return config
})

http.interceptors.response.use(
  resp => {
    const data = resp.data
    if (data && typeof data === 'object' && 'code' in data) {
      if (data.code === 0) return data.data
      if (data.code === 401) {
        clearToken()
        window.location.reload()
      }
      return Promise.reject(new Error(data.message || '请求失败'))
    }
    return data
  },
  err => {
    if (err.response && err.response.status === 401) {
      clearToken()
      window.location.reload()
    }
    return Promise.reject(err)
  }
)

export default http

/* ====== 业务 API ====== */
export const login = (username) => http.post('/user/login', { username })

export const uploadDocument = (file) => {
  const form = new FormData()
  form.append('file', file)
  return http.post('/document/upload', form, { headers: { 'Content-Type': 'multipart/form-data' } })
}

export const listDocuments = () => http.get('/document/list')
export const deleteDocument = (id) => http.delete(`/document/${id}`)

export const listSessions = () => http.get('/chat/sessions')
export const createSession = (title) => http.post('/chat/session', { title: title || '新对话' })
export const listMessages = (sid) => http.get(`/chat/messages/${sid}`)
export const deleteSession = (id) => http.delete(`/chat/session/${id}`)
