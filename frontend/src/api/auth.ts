import { request } from "./client";
import { tokenStorage } from "./tokenStorage";

export interface User {
  id: string;
  email: string;
  display_name: string;
  locale: string;
  timezone: string;
  status: string;
}

export interface TokenPair {
  access_token: string;
  token_type: string;
  refresh_token: string;
  expires_in: number;
}

export async function login(email: string, password: string): Promise<TokenPair> {
  const pair = await request<TokenPair>(
    "/api/v1/auth/login",
    { method: "POST", body: JSON.stringify({ email, password }), credentials: "include" },
    { auth: false },
  );
  tokenStorage.set(pair.access_token);
  return pair;
}

export async function fetchMe(): Promise<User> {
  return request<User>("/api/v1/auth/me");
}

export async function logout(): Promise<void> {
  try {
    await request(
      "/api/v1/auth/logout",
      { method: "POST", credentials: "include" },
      { auth: false },
    );
  } finally {
    tokenStorage.clear();
  }
}
