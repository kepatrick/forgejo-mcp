import { type FormEvent, type ReactNode, useEffect, useState } from 'react'

type Account = {
  id: string
  username: string
  role: 'admin' | 'user'
  must_change_password: boolean
}

type ManagedUser = {
  id: string
  display_name: string
  username: string
  forgejo_username: string
  status: 'pending' | 'active' | 'disabled'
  credential_status: 'configured' | 'not_configured'
  created_at: string
}

type InvitationContext = {
  display_name: string
  username: string
  forgejo_username: string
  expires_at: string
}

type Invitation = {
  id: string
  invitation_url: string
  expires_at: string
}

type ForgejoInstance = {
  configured: boolean
  id: string | null
  display_name: string | null
  base_url: string | null
  verify_tls: boolean | null
  version: string | null
  last_checked_at: string | null
}

type ForgejoConnection = {
  base_url: string
  version: string
  checked_at: string
}

type ForgejoCredential = {
  configured: boolean
  id: string | null
  status: string | null
  forgejo_user_id: number | null
  forgejo_username: string | null
  verified_at: string | null
  activated_at: string | null
}

type ForgejoPrincipal = {
  forgejo_user_id: number
  forgejo_username: string
}

type McpToken = {
  id: string
  user_id: string
  name: string
  description: string | null
  token_prefix: string
  status: 'active' | 'expired' | 'disabled' | 'revoked'
  expires_at: string | null
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
}

type CreatedMcpToken = McpToken & { token: string }
type AdminMcpToken = McpToken & { user_display_name: string; username: string }

type Tool = {
  name: string
  title: string
  description: string
  risk: string
  globally_enabled: boolean
  user_allowed: boolean | null
  effective: boolean | null
}

type ToolNames = { tool_names: string[] }

type ToolInvocation = {
  id: string
  user_display_name: string
  token_name: string
  forgejo_username: string
  tool_name: string
  risk: string
  started_at: string
  duration_ms: number | null
  status: 'pending' | 'succeeded' | 'failed' | 'denied'
  denial_reason: string | null
  error_type: string | null
  target: Record<string, unknown>
  result_summary: Record<string, unknown>
}

type ToolInvocationPage = {
  items: ToolInvocation[]
  page: number
  limit: number
  has_more: boolean
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: 'same-origin', ...init })
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new Error(payload?.detail ?? `Request failed (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

function csrfToken(): string {
  const cookie = document.cookie.split('; ').find((entry) => entry.startsWith('fmcp_csrf='))
  return cookie ? decodeURIComponent(cookie.split('=').slice(1).join('=')) : ''
}

function jsonRequest(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken() },
    body: body === undefined ? undefined : JSON.stringify(body),
  }
}

function invitationToken(): string | null {
  if (!window.location.hash.startsWith('#/invite?')) return null
  return new URLSearchParams(window.location.hash.split('?')[1]).get('token')
}

function Login({ onLogin }: { onLogin: (account: Account) => void }) {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      onLogin(
        await api<Account>('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password }),
        }),
      )
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to sign in')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthCard eyebrow="Secure administration" title="Sign in">
      <form onSubmit={submit} className="form">
        <Field label="Username"><input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></Field>
        <Field label="Password"><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required /></Field>
        {error && <p className="error" role="alert">{error}</p>}
        <button disabled={submitting}>{submitting ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </AuthCard>
  )
}

function ChangePassword({ account, onChanged }: { account: Account; onChanged: (account: Account) => void }) {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [error, setError] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    try {
      onChanged(await api<Account>('/api/auth/change-password', jsonRequest('POST', { current_password: currentPassword, new_password: newPassword })))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to change password')
    }
  }

  return (
    <AuthCard eyebrow={`Signed in as ${account.username}`} title="Change your password">
      <p className="description">The bootstrap password must be replaced before administration can continue.</p>
      <form onSubmit={submit} className="form">
        <Field label="Current password"><input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} autoComplete="current-password" required /></Field>
        <Field label="New password (12+ characters)"><input type="password" minLength={12} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" required /></Field>
        {error && <p className="error" role="alert">{error}</p>}
        <button>Update password</button>
      </form>
    </AuthCard>
  )
}

function InvitationPage({ token }: { token: string }) {
  const [context, setContext] = useState<InvitationContext | null>(null)
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [accepted, setAccepted] = useState(false)

  useEffect(() => {
    api<InvitationContext>('/api/auth/invitations/context', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }),
    }).then(setContext).catch((caught) => setError(caught instanceof Error ? caught.message : 'Invalid invitation'))
  }, [token])

  async function accept(event: FormEvent) {
    event.preventDefault()
    setError('')
    try {
      await api('/api/auth/invitations/accept', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token, password }),
      })
      setAccepted(true)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to accept invitation')
    }
  }

  if (accepted) return <AuthCard eyebrow="Invitation accepted" title="Account ready"><p className="description">Your account is active. Sign in with the password you just created.</p><button onClick={() => window.location.replace('/')}>Continue to sign in</button></AuthCard>
  return (
    <AuthCard eyebrow="Forgejo MCP invitation" title={context ? `Welcome, ${context.display_name}` : 'Checking invitation…'}>
      {context && <><p className="description">Dashboard account <strong>{context.username}</strong> will be linked to Forgejo user <strong>{context.forgejo_username}</strong>.</p><form onSubmit={accept} className="form"><Field label="Create password (12+ characters)"><input type="password" minLength={12} value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" required /></Field><button>Activate account</button></form></>}
      {error && <p className="error" role="alert">{error}</p>}
    </AuthCard>
  )
}

function UserManagement() {
  const [users, setUsers] = useState<ManagedUser[]>([])
  const [displayName, setDisplayName] = useState('')
  const [username, setUsername] = useState('')
  const [forgejoUsername, setForgejoUsername] = useState('')
  const [invitation, setInvitation] = useState<Invitation | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api<ManagedUser[]>('/api/users')
      .then(setUsers)
      .catch((caught) => setError(caught instanceof Error ? caught.message : 'Unable to load users'))
  }, [])

  async function create(event: FormEvent) {
    event.preventDefault(); setError(''); setInvitation(null)
    try {
      const user = await api<ManagedUser>('/api/users', jsonRequest('POST', { display_name: displayName, username, forgejo_username: forgejoUsername }))
      setUsers((current) => [...current, user]); setDisplayName(''); setUsername(''); setForgejoUsername('')
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to create user') }
  }

  async function invite(userId: string) {
    setError('')
    try {
      const created = await api<Invitation>(`/api/users/${userId}/invitations`, jsonRequest('POST'))
      setInvitation({ ...created, invitation_url: new URL(created.invitation_url, window.location.origin).toString() })
    }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to create invitation') }
  }

  async function setEnabled(user: ManagedUser, enabled: boolean) {
    setError('')
    try {
      const updated = await api<ManagedUser>(`/api/users/${user.id}/${enabled ? 'enable' : 'disable'}`, jsonRequest('POST'))
      setUsers((current) => current.map((item) => item.id === updated.id ? updated : item))
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to update user') }
  }

  async function revokeCredential(user: ManagedUser) {
    if (!window.confirm(`Revoke the Forgejo credential for ${user.display_name}?`)) return
    setError('')
    try {
      await api<void>(`/api/users/${user.id}/credential`, jsonRequest('DELETE'))
      setUsers((current) => current.map((item) => item.id === user.id ? { ...item, credential_status: 'not_configured' } : item))
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to revoke credential') }
  }

  return <section className="panel"><div><p className="eyebrow">Administration</p><h2>Users</h2></div><form className="form userForm" onSubmit={create}><Field label="Display name"><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required /></Field><Field label="Dashboard username"><input minLength={3} value={username} onChange={(event) => setUsername(event.target.value)} required /></Field><Field label="Forgejo username"><input value={forgejoUsername} onChange={(event) => setForgejoUsername(event.target.value)} required /></Field><button>Create user</button></form>{error && <p className="error" role="alert">{error}</p>}{invitation && <div className="invitation"><strong>Copy this link now</strong><input readOnly value={invitation.invitation_url} onFocus={(event) => event.target.select()} /><button className="secondary" onClick={() => navigator.clipboard.writeText(invitation.invitation_url)}>Copy link</button></div>}<div className="userList">{users.map((user) => <article className="userRow" key={user.id}><div><strong>{user.display_name}</strong><span>@{user.username} · Forgejo: {user.forgejo_username} · Credential: {user.credential_status}</span></div><span className={`badge badge-${user.status}`}>{user.status}</span><div className="rowActions">{user.credential_status === 'configured' && <button className="secondary danger" onClick={() => revokeCredential(user)}>Revoke PAT</button>}{user.status !== 'disabled' && <button className="secondary" onClick={() => invite(user.id)}>Invite</button>}<button className="secondary" onClick={() => setEnabled(user, user.status === 'disabled')}>{user.status === 'disabled' ? 'Enable' : 'Disable'}</button></div></article>)}</div></section>
}

function ForgejoSettings() {
  const [displayName, setDisplayName] = useState('Forgejo')
  const [baseUrl, setBaseUrl] = useState('')
  const [verifyTls, setVerifyTls] = useState(true)
  const [connection, setConnection] = useState<ForgejoConnection | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    api<ForgejoInstance>('/api/forgejo/instance')
      .then((instance) => {
        if (!instance.configured) return
        setDisplayName(instance.display_name ?? 'Forgejo')
        setBaseUrl(instance.base_url ?? '')
        setVerifyTls(instance.verify_tls ?? true)
        if (instance.base_url && instance.version && instance.last_checked_at) {
          setConnection({ base_url: instance.base_url, version: instance.version, checked_at: instance.last_checked_at })
        }
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : 'Unable to load Forgejo settings'))
  }, [])

  async function run(action: 'test' | 'save') {
    setSubmitting(true); setError(''); setMessage('')
    try {
      if (action === 'test') {
        const result = await api<ForgejoConnection>('/api/forgejo/instance/test', jsonRequest('POST', { base_url: baseUrl, verify_tls: verifyTls }))
        setConnection(result); setBaseUrl(result.base_url)
        setMessage(`Connection successful · Forgejo ${result.version}`)
      } else {
        const saved = await api<ForgejoInstance>('/api/forgejo/instance', jsonRequest('PUT', { display_name: displayName, base_url: baseUrl, verify_tls: verifyTls }))
        if (saved.base_url && saved.version && saved.last_checked_at) {
          setConnection({ base_url: saved.base_url, version: saved.version, checked_at: saved.last_checked_at })
        }
        setBaseUrl(saved.base_url ?? baseUrl); setMessage('Forgejo instance saved')
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Forgejo connection failed')
    } finally { setSubmitting(false) }
  }

  return <section className="panel"><div><p className="eyebrow">External service</p><h2>Forgejo instance</h2></div><p>Connect this MCP server to the company Forgejo service. User credentials are configured separately.</p><div className="form userForm"><Field label="Display name"><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required /></Field><Field label="Base URL"><input type="url" placeholder="https://git.company.internal" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} required /></Field><label className="checkbox"><input type="checkbox" checked={verifyTls} onChange={(event) => setVerifyTls(event.target.checked)} /><span>Verify TLS certificate</span></label><div className="rowActions"><button className="secondary" disabled={submitting || !baseUrl} onClick={() => run('test')}>Test connection</button><button disabled={submitting || !baseUrl || !displayName} onClick={() => run('save')}>Test and save</button></div></div>{connection && <p className="connection">Connected to <strong>{connection.base_url}</strong> · version {connection.version}</p>}{message && <p className="success" role="status">{message}</p>}{error && <p className="error" role="alert">{error}</p>}</section>
}

function MyForgejoCredential() {
  const [credential, setCredential] = useState<ForgejoCredential | null>(null)
  const [token, setToken] = useState('')
  const [principal, setPrincipal] = useState<ForgejoPrincipal | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    api<ForgejoCredential>('/api/me/credential')
      .then(setCredential)
      .catch((caught) => setError(caught instanceof Error ? caught.message : 'Unable to load credential status'))
  }, [])

  async function run(action: 'test' | 'save') {
    setSubmitting(true); setError(''); setMessage(''); setPrincipal(null)
    try {
      if (action === 'test') {
        const verified = await api<ForgejoPrincipal>('/api/me/credential/test', jsonRequest('POST', { token }))
        setPrincipal(verified); setMessage(`Verified as ${verified.forgejo_username}`)
      } else {
        const saved = await api<ForgejoCredential>('/api/me/credential', jsonRequest('PUT', { token }))
        setCredential(saved); setToken(''); setMessage('Forgejo credential encrypted and saved')
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Credential verification failed')
    } finally { setSubmitting(false) }
  }

  async function revoke() {
    if (!window.confirm('Revoke your saved Forgejo credential?')) return
    setError(''); setMessage('')
    try {
      await api<void>('/api/me/credential', jsonRequest('DELETE'))
      setCredential({ configured: false, id: null, status: null, forgejo_user_id: null, forgejo_username: null, verified_at: null, activated_at: null })
      setToken(''); setPrincipal(null); setMessage('Forgejo credential revoked')
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to revoke credential') }
  }

  return <section className="panel"><div><p className="eyebrow">Personal access</p><h2>My Forgejo credential</h2></div><p>Your PAT is verified against your assigned Forgejo username, encrypted, and never shown again.</p>{credential?.configured && <div className="credentialSummary"><strong>{credential.forgejo_username}</strong><span>Forgejo user ID {credential.forgejo_user_id}</span><span>Verified {credential.verified_at ? new Date(credential.verified_at).toLocaleString() : ''}</span></div>}<div className="form"><Field label={credential?.configured ? 'New PAT for rotation' : 'Forgejo personal access token'}><input type="password" value={token} onChange={(event) => setToken(event.target.value)} autoComplete="off" required /></Field><div className="rowActions"><button className="secondary" disabled={submitting || !token} onClick={() => run('test')}>Test PAT</button><button disabled={submitting || !token} onClick={() => run('save')}>{credential?.configured ? 'Verify and rotate' : 'Verify and save'}</button>{credential?.configured && <button className="secondary danger" onClick={revoke}>Revoke saved PAT</button>}</div></div>{principal && <p className="connection">Verified Forgejo principal: <strong>{principal.forgejo_username}</strong> ({principal.forgejo_user_id})</p>}{message && <p className="success" role="status">{message}</p>}{error && <p className="error" role="alert">{error}</p>}</section>
}

function MyMcpTokens({ onTokensChanged }: { onTokensChanged: () => void }) {
  const [tokens, setTokens] = useState<McpToken[]>([])
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [expiresAt, setExpiresAt] = useState('')
  const [createdToken, setCreatedToken] = useState<string | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api<McpToken[]>('/api/me/mcp-tokens')
      .then(setTokens)
      .catch((caught) => setError(caught instanceof Error ? caught.message : 'Unable to load MCP tokens'))
  }, [])

  async function create(event: FormEvent) {
    event.preventDefault(); setError(''); setCreatedToken(null)
    try {
      const created = await api<CreatedMcpToken>('/api/me/mcp-tokens', jsonRequest('POST', {
        name,
        description: description || null,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      }))
      setTokens((current) => [created, ...current]); setCreatedToken(created.token)
      setName(''); setDescription(''); setExpiresAt(''); onTokensChanged()
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to create MCP token') }
  }

  async function revoke(token: McpToken) {
    if (!window.confirm(`Revoke MCP token “${token.name}”?`)) return
    setError('')
    try {
      await api<void>(`/api/me/mcp-tokens/${token.id}`, jsonRequest('DELETE'))
      setTokens((current) => current.map((item) => item.id === token.id ? { ...item, status: 'revoked', revoked_at: new Date().toISOString() } : item))
      onTokensChanged()
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to revoke MCP token') }
  }

  return <section className="panel"><div><p className="eyebrow">MCP client access</p><h2>My MCP tokens</h2></div><p>Create a separate token for each MCP client. The full token is shown only once.</p><form className="form tokenForm" onSubmit={create}><Field label="Token name"><input value={name} maxLength={120} onChange={(event) => setName(event.target.value)} required /></Field><Field label="Description (optional)"><input value={description} maxLength={500} onChange={(event) => setDescription(event.target.value)} /></Field><Field label="Expires at (optional)"><input type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} /></Field><button>Create token</button></form>{createdToken && <div className="secretReveal"><strong>Copy this token now. It will not be shown again.</strong><input readOnly value={createdToken} onFocus={(event) => event.target.select()} /><button className="secondary" onClick={() => navigator.clipboard.writeText(createdToken)}>Copy token</button></div>}{error && <p className="error" role="alert">{error}</p>}<div className="userList">{tokens.map((token) => <article className="userRow" key={token.id}><div><strong>{token.name}</strong><span>{token.token_prefix}… · Created {new Date(token.created_at).toLocaleString()}{token.expires_at ? ` · Expires ${new Date(token.expires_at).toLocaleString()}` : ''}</span>{token.description && <span>{token.description}</span>}</div><span className={`badge badge-${token.status}`}>{token.status}</span><div className="rowActions">{token.status === 'active' && <button className="secondary danger" onClick={() => revoke(token)}>Revoke</button>}</div></article>)}</div></section>
}

function MyToolPermissions({ tokenRevision }: { tokenRevision: number }) {
  const [tokens, setTokens] = useState<McpToken[]>([])
  const [tools, setTools] = useState<Tool[]>([])
  const [tokenId, setTokenId] = useState('')
  const [grants, setGrants] = useState<string[]>([])
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([api<McpToken[]>('/api/me/mcp-tokens'), api<Tool[]>('/api/me/tools')])
      .then(([loadedTokens, loadedTools]) => {
        setTokens(loadedTokens.filter((token) => token.status === 'active'))
        setTools(loadedTools); setTokenId(''); setGrants([])
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : 'Unable to load tool permissions'))
  }, [tokenRevision])

  async function selectToken(selected: string) {
    setTokenId(selected); setMessage(''); setError('')
    if (!selected) { setGrants([]); return }
    try {
      setGrants((await api<ToolNames>(`/api/me/mcp-tokens/${selected}/tools`)).tool_names)
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to load token grants') }
  }

  function toggle(toolName: string, checked: boolean) {
    setGrants((current) => checked ? [...current, toolName] : current.filter((name) => name !== toolName))
  }

  function setAllGrants(enabled: boolean) {
    setGrants(enabled ? tools.filter((tool) => tool.user_allowed && tool.globally_enabled).map((tool) => tool.name) : [])
  }

  async function save() {
    setError(''); setMessage('')
    try {
      const saved = await api<ToolNames>(`/api/me/mcp-tokens/${tokenId}/tools`, jsonRequest('PUT', { tool_names: grants }))
      setGrants(saved.tool_names); setMessage('Token tool permissions saved')
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to save token grants') }
  }

  const availableTools = tools.filter((tool) => tool.user_allowed)
  return <section className="panel"><div><p className="eyebrow">Least privilege</p><h2>Token tool permissions</h2></div><p>Grant each MCP token only the tools it needs. Admin-defined user allowances remain the maximum.</p><div className="form"><Field label="MCP token"><select value={tokenId} onChange={(event) => selectToken(event.target.value)}><option value="">Select a token</option>{tokens.map((token) => <option key={token.id} value={token.id}>{token.name}</option>)}</select></Field>{tokenId && <div className="toolList"><div className="bulkActions"><button type="button" className="secondary" disabled={!availableTools.some((tool) => tool.globally_enabled)} onClick={() => setAllGrants(true)}>Select available</button><button type="button" className="secondary" disabled={grants.length === 0} onClick={() => setAllGrants(false)}>Clear all</button></div>{availableTools.length > 0 && <div className="tokenToolGrid">{availableTools.map((tool) => <label className={`toolChoice${tool.globally_enabled ? '' : ' toolChoice-disabled'}`} key={tool.name}><input type="checkbox" checked={grants.includes(tool.name)} disabled={!tool.globally_enabled} onChange={(event) => toggle(tool.name, event.target.checked)} /><span><strong>{tool.title}</strong><small>{tool.risk} · {tool.globally_enabled ? 'globally enabled' : 'globally unavailable'}</small></span></label>)}</div>}{availableTools.length === 0 && <p>No tools have been allowed for your account.</p>}<button onClick={save}>Save permissions</button></div>}</div>{message && <p className="success" role="status">{message}</p>}{error && <p className="error" role="alert">{error}</p>}</section>
}

function AdminTools() {
  const [tools, setTools] = useState<Tool[]>([])
  const [users, setUsers] = useState<ManagedUser[]>([])
  const [allowances, setAllowances] = useState<Record<string, string[]>>({})
  const [updatingGlobals, setUpdatingGlobals] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([api<Tool[]>('/api/tools'), api<ManagedUser[]>('/api/users')])
      .then(async ([loadedTools, loadedUsers]) => {
        setTools(loadedTools); setUsers(loadedUsers)
        const loaded = await Promise.all(loadedUsers.map(async (user) => [user.id, (await api<ToolNames>(`/api/users/${user.id}/tools`)).tool_names] as const))
        setAllowances(Object.fromEntries(loaded))
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : 'Unable to load tools'))
  }, [])

  async function setGlobal(tool: Tool, enabled: boolean) {
    setError('')
    try {
      const updated = await api<Tool>(`/api/tools/${tool.name}`, jsonRequest('PUT', { enabled }))
      setTools((current) => current.map((item) => item.name === updated.name ? updated : item))
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to update global tool setting') }
  }

  async function setAllGlobal(enabled: boolean) {
    setUpdatingGlobals(true); setError('')
    try {
      const updated = await Promise.all(tools.map((tool) => api<Tool>(`/api/tools/${tool.name}`, jsonRequest('PUT', { enabled }))))
      setTools(updated)
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to update global tool settings') }
    finally { setUpdatingGlobals(false) }
  }

  function toggleAllowance(userId: string, toolName: string, checked: boolean) {
    setAllowances((current) => ({ ...current, [userId]: checked ? [...(current[userId] ?? []), toolName] : (current[userId] ?? []).filter((name) => name !== toolName) }))
  }

  function setAllAllowances(userId: string, enabled: boolean) {
    setAllowances((current) => ({ ...current, [userId]: enabled ? tools.map((tool) => tool.name) : [] }))
  }

  async function saveAllowances(userId: string) {
    setError('')
    try {
      const saved = await api<ToolNames>(`/api/users/${userId}/tools`, jsonRequest('PUT', { tool_names: allowances[userId] ?? [] }))
      setAllowances((current) => ({ ...current, [userId]: saved.tool_names }))
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to update user allowances') }
  }

  return <section className="panel"><div><p className="eyebrow">Authorization</p><h2>Tools</h2></div><p>New tools are globally disabled. User allowances define the maximum tools each user may grant to a token.</p>{error && <p className="error" role="alert">{error}</p>}<div className="bulkActions"><button className="secondary" disabled={updatingGlobals || tools.length === 0} onClick={() => setAllGlobal(true)}>Enable all globally</button><button className="secondary" disabled={updatingGlobals || tools.length === 0} onClick={() => setAllGlobal(false)}>Disable all globally</button></div><div className="toolList">{tools.map((tool) => <article className="toolRow" key={tool.name}><div><strong>{tool.title}</strong><span>{tool.name} · {tool.risk}</span><small>{tool.description}</small></div><label className="switchChoice"><input type="checkbox" checked={tool.globally_enabled} disabled={updatingGlobals} onChange={(event) => setGlobal(tool, event.target.checked)} /> Globally enabled</label></article>)}</div><div className="userList">{users.map((user) => <article className="allowanceRow" key={user.id}><div className="allowanceHeader"><div className="allowanceIdentity"><strong>{user.display_name}</strong><span>@{user.username}</span></div><div className="bulkActions"><button className="secondary compact" onClick={() => setAllAllowances(user.id, true)}>Select all</button><button className="secondary compact" onClick={() => setAllAllowances(user.id, false)}>Clear all</button></div></div><div className="allowanceTools">{tools.map((tool) => <label className="toolChoice" key={tool.name}><input type="checkbox" checked={(allowances[user.id] ?? []).includes(tool.name)} onChange={(event) => toggleAllowance(user.id, tool.name, event.target.checked)} /><span>{tool.title}</span></label>)}</div><div className="allowanceFooter"><span>{(allowances[user.id] ?? []).length} of {tools.length} selected</span><button className="secondary" onClick={() => saveAllowances(user.id)}>Save allowance</button></div></article>)}</div></section>
}

function AdminMcpTokens() {
  const [tokens, setTokens] = useState<AdminMcpToken[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    api<AdminMcpToken[]>('/api/mcp-tokens')
      .then(setTokens)
      .catch((caught) => setError(caught instanceof Error ? caught.message : 'Unable to load MCP tokens'))
  }, [])

  async function revoke(token: AdminMcpToken) {
    if (!window.confirm(`Revoke MCP token “${token.name}” for ${token.user_display_name}?`)) return
    setError('')
    try {
      await api<void>(`/api/mcp-tokens/${token.id}`, jsonRequest('DELETE'))
      setTokens((current) => current.map((item) => item.id === token.id ? { ...item, status: 'revoked', revoked_at: new Date().toISOString() } : item))
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to revoke MCP token') }
  }

  return <section className="panel"><div><p className="eyebrow">Administration</p><h2>MCP tokens</h2></div><p>Review token metadata and revoke access. Token secrets are never available to administrators.</p>{error && <p className="error" role="alert">{error}</p>}<div className="userList">{tokens.map((token) => <article className="userRow" key={token.id}><div><strong>{token.name}</strong><span>{token.user_display_name} (@{token.username}) · {token.token_prefix}…</span></div><span className={`badge badge-${token.status}`}>{token.status}</span><div className="rowActions">{token.status === 'active' && <button className="secondary danger" onClick={() => revoke(token)}>Revoke</button>}</div></article>)}</div></section>
}

function InvocationAudit({ role }: { role: Account['role'] }) {
  const [records, setRecords] = useState<ToolInvocation[]>([])
  const [users, setUsers] = useState<ManagedUser[]>([])
  const [tools, setTools] = useState<Tool[]>([])
  const [userId, setUserId] = useState('')
  const [status, setStatus] = useState('')
  const [toolName, setToolName] = useState('')
  const [startedAfter, setStartedAfter] = useState('')
  const [startedBefore, setStartedBefore] = useState('')
  const [hasMore, setHasMore] = useState(false)
  const [error, setError] = useState('')

  async function fetchRecords(query: URLSearchParams) {
    const base = role === 'admin' ? '/api/audit/tool-invocations' : '/api/me/audit/tool-invocations'
    const page = await api<ToolInvocationPage>(`${base}?${query}`)
    setRecords(page.items); setHasMore(page.has_more)
  }

  async function load() {
    setError('')
    const query = new URLSearchParams({ limit: '100' })
    if (startedAfter && startedBefore && startedAfter > startedBefore) {
      setError('Start date must not be later than end date')
      return
    }
    if (role === 'admin' && userId) query.set('user_id', userId)
    if (status) query.set('status', status)
    if (toolName) query.set('tool_name', toolName)
    if (startedAfter) query.set('started_after', new Date(`${startedAfter}T00:00:00`).toISOString())
    if (startedBefore) {
      const endExclusive = new Date(`${startedBefore}T00:00:00`)
      endExclusive.setDate(endExclusive.getDate() + 1)
      query.set('started_before', endExclusive.toISOString())
    }
    try { await fetchRecords(query) }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to load invocation audit') }
  }

  useEffect(() => {
    const base = role === 'admin' ? '/api/audit/tool-invocations' : '/api/me/audit/tool-invocations'
    const toolBase = role === 'admin' ? '/api/tools' : '/api/me/tools'
    api<ToolInvocationPage>(`${base}?limit=100`)
      .then((page) => { setRecords(page.items); setHasMore(page.has_more) })
      .catch((caught) => setError(caught instanceof Error ? caught.message : 'Unable to load invocation audit'))
    api<Tool[]>(toolBase)
      .then(setTools)
      .catch((caught) => setError(caught instanceof Error ? caught.message : 'Unable to load tool options'))
    if (role === 'admin') {
      api<ManagedUser[]>('/api/users')
        .then(setUsers)
        .catch((caught) => setError(caught instanceof Error ? caught.message : 'Unable to load user options'))
    }
  }, [role])

  return <section className="panel"><div><p className="eyebrow">Audit</p><h2>Tool invocations</h2></div><p>{role === 'admin' ? 'Review invocation records across all users.' : 'Review calls made with your MCP tokens.'}</p><div className="auditFilters">{role === 'admin' && <Field label="User"><select value={userId} onChange={(event) => setUserId(event.target.value)}><option value="">All users</option>{users.map((user) => <option key={user.id} value={user.id}>{user.display_name} (@{user.username})</option>)}</select></Field>}<Field label="Tool"><select value={toolName} onChange={(event) => setToolName(event.target.value)}><option value="">All tools</option>{tools.map((tool) => <option key={tool.name} value={tool.name}>{tool.title}</option>)}</select></Field><Field label="Status"><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option><option value="succeeded">Succeeded</option><option value="failed">Failed</option><option value="denied">Denied</option><option value="pending">Pending</option></select></Field><Field label="Started on or after"><input type="date" value={startedAfter} max={startedBefore || undefined} onChange={(event) => setStartedAfter(event.target.value)} /></Field><Field label="Started on or before"><input type="date" value={startedBefore} min={startedAfter || undefined} onChange={(event) => setStartedBefore(event.target.value)} /></Field><button className="secondary" onClick={load}>Apply filters</button></div>{error && <p className="error" role="alert">{error}</p>}<p className="auditCount">Showing {records.length} invocation{records.length === 1 ? '' : 's'}{hasMore ? ' · More records exist; use filters to narrow the results.' : ''}</p><div className="userList">{records.map((record) => <article className="auditRow" key={record.id}><div><strong>{record.tool_name}</strong><span>{role === 'admin' ? `${record.user_display_name} · ` : ''}{record.token_name} · {new Date(record.started_at).toLocaleString()}</span><small>{Object.keys(record.target).length ? JSON.stringify(record.target) : 'No resource target'}{record.denial_reason ? ` · ${record.denial_reason}` : ''}{record.error_type ? ` · ${record.error_type}` : ''}</small></div><span className={`badge badge-${record.status}`}>{record.status}</span><span>{record.duration_ms ?? '—'} ms</span></article>)}{records.length === 0 && <p>No invocation records match these filters.</p>}</div></section>
}

function Dashboard({ account, onLogout }: { account: Account; onLogout: () => void }) {
  const [tokenRevision, setTokenRevision] = useState(0)
  async function logout() { await api<void>('/api/auth/logout', jsonRequest('POST')); onLogout() }
  return <main className="dashboard"><header className="topbar"><div><span className="brand">Forgejo MCP</span><span className="role">{account.role}</span></div><div className="actions"><span>{account.username}</span><button className="secondary" onClick={logout}>Sign out</button></div></header><div className="content"><section className="hero"><p className="eyebrow">Internal developer platform</p><h1>Dashboard</h1><p className="description">Manage the Forgejo connection, internal identities, credentials, and MCP client access.</p></section>{account.role === 'admin' ? <><ForgejoSettings /><UserManagement /><AdminTools /><AdminMcpTokens /><InvocationAudit role="admin" /></> : <><MyForgejoCredential /><MyMcpTokens onTokensChanged={() => setTokenRevision((current) => current + 1)} /><MyToolPermissions tokenRevision={tokenRevision} /><InvocationAudit role="user" /></>}</div></main>
}

function Field({ label, children }: { label: string; children: ReactNode }) { return <label><span>{label}</span>{children}</label> }
function AuthCard({ eyebrow, title, children }: { eyebrow: string; title: string; children: ReactNode }) { return <main className="shell"><section className="card authCard"><p className="eyebrow">{eyebrow}</p><h1>{title}</h1>{children}</section></main> }

export function App() {
  const token = invitationToken()
  const [account, setAccount] = useState<Account | null>(null)
  const [loading, setLoading] = useState(!token)
  useEffect(() => { if (!token) api<Account>('/api/auth/me').then(setAccount).catch(() => setAccount(null)).finally(() => setLoading(false)) }, [token])
  if (token) return <InvitationPage token={token} />
  if (loading) return <AuthCard eyebrow="Forgejo MCP" title="Loading…"><p className="description">Checking your session.</p></AuthCard>
  if (!account) return <Login onLogin={setAccount} />
  if (account.must_change_password) return <ChangePassword account={account} onChanged={setAccount} />
  return <Dashboard account={account} onLogout={() => setAccount(null)} />
}
