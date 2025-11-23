# Authentication & Session Tokens

Mini RAG now supports offline-ready sessions via self-issued JWT access tokens. Users log in once, and as long as the token remains valid, page reloads no longer require re-entering credentials.

## Backend Changes

- `/api/v1/auth/login` (JSON) accepts `{ "username": "...", "password": "..." }` and returns:

  ```json
  {
    "access_token": "<JWT>",
    "token_type": "bearer",
    "expires_in": 86400,
    "user": { "id": 1, "username": "admin", "is_admin": true, "department": "Admins" }
  }
  ```

- The token encodes `user_id`, `username`, and `is_admin` and expires after `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (default 1440 minutes = 24h).
- `routes/dependencies.get_current_user` now accepts both Bearer tokens and legacy Basic Auth. Existing API scripts that still use Basic headers continue to work.

### Configuration

Set the following in `.env` (or rely on defaults for development):

```
JWT_SECRET_KEY="change-me"
JWT_ALGORITHM="HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

Restart the FastAPI server after changing secrets. Rotate `JWT_SECRET_KEY` to invalidate all sessions.

## Frontend Changes

- `LoginPage` now posts to `/api/v1/auth/login`. On success it stores the token and expiry inside `SettingsContext` / localStorage (encrypted passwords are no longer required unless "remember password" was previously enabled).
- `useHttpClient` automatically sends `Authorization: Bearer <token>` for all requests, falling back to Basic only if no token exists. When a request returns `401` due to an expired/invalid token, the stored token is cleared so the user is redirected to `/login`.
- The logout button clears the token, expiry, and cached user identity.
- Route protection now checks for either stored basic credentials or a valid (non-expired) token so refreshing the page keeps you signed in until the token expires.

## Activation Steps

1. Deploy the updated backend and frontend.
2. Set `JWT_SECRET_KEY` in `.env` (production) before restarting the API service.
3. Inform users that they only need to log in once per 24h (or whatever expiry you configure). Sessions persist across browser reloads until the token expires or they log out.
4. Optional: update automation scripts to switch from Basic Auth to Bearer tokens by calling the login endpoint first.

## Future Enhancements

- Add refresh tokens if you need longer-lived sessions without asking users to log in again.
- Integrate with an external IdP (OAuth/OIDC) if you later require SSO.
