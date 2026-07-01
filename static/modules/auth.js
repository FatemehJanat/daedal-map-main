/**
 * Open-core guest/local auth shim.
 *
 * The public runtime does not ship the private hosted account stack or the
 * DaedalMap Supabase browser client. Self-host users can add their own auth
 * layer separately if they want one.
 */

const AUTH_EVENT = 'countymap-auth-changed';
const AUTH_BOOT_EVENT = 'countymap-auth-boot-settled';
const GUEST_MAX_AGE_MS = 24 * 60 * 60 * 1000;

let authBootPending = false;
let authBootSettled = true;

function dispatchAuthChanged() {
  window.dispatchEvent(new CustomEvent(AUTH_EVENT, {
    detail: {
      isAuthenticated: false,
      user: null,
    },
  }));
}

function dispatchBootSettled() {
  window.dispatchEvent(new CustomEvent(AUTH_BOOT_EVENT, {
    detail: {
      isAuthenticated: false,
      user: null,
    },
  }));
}

dispatchBootSettled();
dispatchAuthChanged();

export function onAuthChanged(callback) {
  if (typeof callback !== 'function') return () => {};
  const listener = (event) => callback(event);
  window.addEventListener(AUTH_EVENT, listener);
  callback(new CustomEvent(AUTH_EVENT, {
    detail: {
      isAuthenticated: false,
      user: null,
    },
  }));
  return () => window.removeEventListener(AUTH_EVENT, listener);
}

export function isAuthenticated() {
  return false;
}

export function isAuthBootPending() {
  return authBootPending;
}

export async function waitForAuthBoot(timeoutMs = 2500) {
  void timeoutMs;
  authBootPending = false;
  authBootSettled = true;
  return {
    isAuthenticated: false,
    user: null,
  };
}

export function getCurrentUser() {
  return null;
}

export function getAccessToken() {
  return null;
}

export async function refreshRuntimeSession({ forceSessionRefresh = false, forceProfileRefresh = false } = {}) {
  void forceSessionRefresh;
  void forceProfileRefresh;
  authBootPending = false;
  authBootSettled = true;
  return null;
}

export async function ensureRuntimeAccessToken() {
  return null;
}

export function getStorageNamespace() {
  return 'guest';
}

export function getSessionMaxAgeMs() {
  return GUEST_MAX_AGE_MS;
}

export function getCurrentProfile() {
  return null;
}

export function getSupabaseClient() {
  return null;
}

export function getSiteBaseUrl() {
  return '';
}
