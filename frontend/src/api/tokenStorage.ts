/** 令牌本地存储（spec §18.3）：access token 存内存/localStorage；refresh token 走 HttpOnly Cookie，不入 JS 可读存储。 */

const ACCESS_KEY = "ar.access_token";

export const tokenStorage = {
  getAccess: () => localStorage.getItem(ACCESS_KEY),
  // refresh token 已 HttpOnly Cookie 化，不再从 localStorage 读
  getRefresh: () => null,
  set(access: string | null, _refresh: string | null = null) {
    if (access) localStorage.setItem(ACCESS_KEY, access);
    else localStorage.removeItem(ACCESS_KEY);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
  },
};
