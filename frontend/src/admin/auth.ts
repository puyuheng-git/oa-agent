import { reactive } from 'vue'
import { http, setCsrfToken } from '@/shared/http'

export interface Me {
  user: { id: number; username: string; display_name: string }
  roles: string[]
  perms: string[]
  csrf_token: string
}

export const auth = reactive<{ me: Me | null; loaded: boolean }>({ me: null, loaded: false })

function apply(me: Me | null) {
  auth.me = me
  auth.loaded = true
  setCsrfToken(me?.csrf_token ?? '')
}

export async function loadMe(): Promise<Me | null> {
  try {
    apply(await http.get<Me>('/v1/admin/auth/me'))
  } catch {
    apply(null)
  }
  return auth.me
}

export async function login(username: string, password: string) {
  apply(await http.post<Me>('/v1/admin/auth/login', { username, password }))
}

export async function logout() {
  try {
    await http.post('/v1/admin/auth/logout')
  } finally {
    apply(null)
  }
}

export function can(perm: string): boolean {
  return !!auth.me?.perms.includes(perm)
}
