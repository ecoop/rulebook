// #175: the build THIS bundle was compiled at, baked in by Vite from the
// Dockerfile web-builder's build-args (VITE_BUILD_NUM / VITE_GIT_SHA). The
// frontend otherwise only knows the SERVER's build (via /meta), so it can't
// tell "am I current?" — the version popup would show the server's number even
// while the tab runs older code. "?" when not injected: local `npm run dev`, or
// the --no-cache / --source deploy path that can't pass build-args.
const env = import.meta.env as Record<string, string | undefined>

export const CLIENT_BUILD = env.VITE_BUILD_NUM || '?'
export const CLIENT_SHA = env.VITE_GIT_SHA || ''
export const CLIENT_BUILD_KNOWN = CLIENT_BUILD !== '?'
