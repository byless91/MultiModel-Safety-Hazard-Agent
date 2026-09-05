import axios from 'axios'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api/v1',
  timeout: 90000,
})

