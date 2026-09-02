# Audit de sécurité externe — forgejo-mcp (fork)

> Note Claude — audit en lecture seule réalisé le 2026-09-02 sur un checkout local du fork, par 4 passes parallèles (malware/supply-chain, auth/OAuth 2.1, crypto/credentials, couche outils/client Forgejo), croisées avec l'auto-audit du dépôt (`docs/security/security-audit-2026-08-31.md`). Aucun fichier du code n'a été modifié.

---

## Disposition après remédiation

> Cette section a été ajoutée après l'audit externe. Le rapport Claude original est conservé intégralement en dessous comme photographie du code avant correctif. « Corrigé » désigne ici le patch de la branche `compat/forgejo-16.0.3`; les risques que l'application ne peut pas supprimer seule restent explicitement classés comme résiduels.

| # | Disposition | Correctif / risque résiduel |
|---|---|---|
| 1 — Haute, dot-segments | **Corrigé** | `.` et `..` sont refusés pour owner, organization, repository et refs par les schémas MCP et par la validation du client Forgejo, avant toute construction d'URL (`forgejo/client.py:2232-2267`, `tools/registry.py:90-158`). Des tests témoins couvrent le client et les schémas. |
| 2 — Haute, allowlist vide | **Corrigé** | Une allowlist Forgejo vide refuse désormais toute connexion dans tous les environnements (`config.py:139-148`). Production continue en plus à refuser le démarrage sans allowlist. |
| 3 — Moyenne, IP/proxy/rate limit | **Corrigé avec limite documentée** | `X-Forwarded-For` n'est accepté que depuis `FMCP_TRUSTED_PROXY_CIDRS`, puis parcouru de droite à gauche (`auth/client_ip.py:10-49`). Les tables mémoire sont bornées, verrouillées et purgées (`auth/rate_limit.py:9-131`). Elles restent mono-processus et sont remises à zéro au redémarrage. |
| 4 — Moyenne, credentials dans `clone_addr` | **Corrigé** | Les user-info de toute URL sont neutralisées récursivement avant l'écriture du reçu d'audit, y compris quand la validation de l'outil échoue ensuite (`audit/redaction.py:18-76`). |
| 5 — Moyenne, contenu des commits | **Corrigé** | Chaque `changes[].content` est remplacé avant persistance par un indicateur de redaction, sa taille UTF-8 et son SHA-256 (`audit/redaction.py:44-70`). |
| 6 — Moyenne, `verify_tls=false` | **Corrigé** | Le choix Dashboard ne suffit plus : il exige l'opt-in de déploiement distinct `FMCP_ALLOW_UNVERIFIED_FORGEJO_TLS=true` (`config.py:33`, `application/forgejo_instance_service.py:35-45`). La valeur par défaut reste `false`. |
| 7 — Moyenne composite, migration/supply-chain/exposition | **Partiellement corrigé, résidu documenté** | Le Compose publie l'App et le Forgejo de test sur loopback par défaut et désactive la confiance implicite d'Uvicorn dans les proxy headers (`deploy/compose.yaml:52-54,102-105`). La résolution DNS finale des migrations reste effectuée par Forgejo : sa politique de migration et les contrôles d'egress restent obligatoires. Images et Actions restent versionnées par tags, pas par digests/SHA immuables. |
| 8–17 — Faibles | **Réduits ou documentés** | Les clés `api_key`, `private_key` et `passwd` sont maintenant sensibles sans utiliser le fragment dangereux `pat`; les limiteurs sont bornés. Les TTL/replay/session/rotation et autres limites faibles restent dans les limitations connues lorsqu'ils ne justifient pas une modification de compatibilité. |

### Verdict après patch

- **Critique : 0** constat connu.
- **Haute : 0** non corrigée parmi les deux constats externes.
- **Moyenne :** aucun défaut applicatif confirmé laissé sans traitement ; demeurent les risques opérationnels explicitement documentés (résolution DNS Forgejo, pinning immuable, état mémoire mono-réplique et terminaison TLS opérateur).
- **Permissions :** aucun scope PAT Forgejo, outil MCP, grant MCP ou permission GitHub supplémentaire n'est ajouté par ces correctifs.

### Validation après patch

- Python : **120 tests réussis**, 1 E2E à credentials externes ignoré ; migrations PostgreSQL appliquées sur une base jetable.
- Qualité : Ruff check/format et MyPy strict réussis ; ESLint, TypeScript et build Vite réussis.
- Dépendances : `pip-audit` et `npm audit` rapportent **0 vulnérabilité connue**.
- Analyse statique : Bandit rapporte **0 moyen / 0 élevé** ; ses 24 alertes basses sont des asserts de narrowing ou des littéraux de protocole examinés.
- Secrets : Gitleaks rapporte **0 fuite** dans le worktree et dans les 14 commits publiés ; les candidats detect-secrets ont été classés comme placeholders, credentials E2E synthétiques, exemples de redaction ou checksums.
- E2E : les **50 outils** passent contre Forgejo 16.0.2 et 16.0.3, avec login, repositories, branches, commits, pull requests, issues, releases, files, search, webhooks, Actions, OAuth et MCP `2025-06-18`.
- Swagger : 2 différences structurelles seulement — version et champs requis de `IssueMeta` — avec **0 différence d'endpoint**.

---

## 🎯 Verdict global

**Aucun malware, aucune backdoor, aucune dépendance piégée.** Code de facture professionnelle, architecture volontairement fail-closed, la plupart des revendications de sécurité sont vérifiées dans le code.

Mais : **2 failles HAUTES** (dont une qui **réfute l'auto-audit inclus dans le dépôt**), **5 MOYENNES**, une dizaine de BASSES — à traiter avant usage en production critique.

### Tableau récapitulatif

| # | Sévérité | Constat | Emplacement |
|---|---|---|---|
| 1 | 🔴 **HAUTE** | Traversée par dot-segments `.`/`..` dans `owner`/`repo`/refs → un grant d'outil ne borne plus l'endpoint API réellement appelé | `forgejo/client.py:2257-2266, 2232-2240, 1743-1746` ; `tools/registry.py:89-90` |
| 2 | 🔴 **HAUTE** | Allowlist d'URLs Forgejo vide = tout permis hors production → re-pointage d'instance et exfiltration des PAT | `config.py:125-133` |
| 3 | 🟠 MOYENNE | Rate limiting keyé sur l'IP directe, inopérant/DoS-able derrière un reverse proxy (déploiement prod normal) | `api/auth.py:105-107`, `api/oauth.py:78,208`, `api/invitations.py:34-36` |
| 4 | 🟠 MOYENNE | Credential embarqué dans `clone_addr` persisté **en clair dans l'audit avant** d'être rejeté par la validation | `mcp/server.py:182-196`, `audit/redaction.py`, `forgejo/client.py:2115-2118` |
| 5 | 🟠 MOYENNE | Contenus de fichiers commités archivés jusqu'à 4 Ko/champ dans l'audit (un `.env` commité y laisse ses secrets) | `audit/redaction.py:51-53` |
| 6 | 🟠 MOYENNE | `verify_tls=false` librement activable par l'admin, sans flag de déploiement (incohérent avec HTTP clair) | `api/forgejo_instance.py:16` |
| 7 | 🟠 MOYENNE | Anti-SSRF migration sans résolution DNS + images Docker pinnées par tag mutable + conteneur `0.0.0.0:8000` sans TLS imposé | `forgejo/client.py:2104-2141`, `deploy/Dockerfile`, `deploy/compose.yaml:50-52` |
| 8-17 | 🟡 BASSE | Voir sections détaillées | — |

---

## 1. 🧬 Malware / supply-chain — PROPRE

### Code Python (src/, scripts/, migrations/, tests/)

- **eval/exec/compile/\_\_import\_\_/marshal/pickle** : aucune occurrence.
- **getattr dynamique** : un seul (`application/forgejo_tool_service.py:379`), dispatch interne vers les méthodes du client, noms issus du registre codé en dur. Bénin.
- **base64** : uniquement encodage de contenu de fichiers (API Forgejo), clé de chiffrement, PKCE dans les tests. Jamais suivi d'exécution.
- **subprocess** : un seul usage (`tests/e2e/full_docker_flow.py:937`), banc E2E local. Légitime.
- **sockets** : `socket.getaddrinfo` dans `oauth_service.py:870-874` est une **garde anti-SSRF** (rejet des adresses non globales), pas une exfiltration.
- Aucun accès `~/.ssh`, `~/.aws`, aucun `os.environ` direct dans `src/` (config pydantic-settings préfixe `FMCP_`), aucune écriture hors projet.

### Domaines / IP codés en dur — liste exhaustive

| Domaine/IP | Emplacements | Appréciation |
|---|---|---|
| `127.0.0.1` / `localhost` / `0.0.0.0` | config, vite.config.ts, scripts, compose | ✅ défauts locaux/bind |
| `*.test`, `attacker.example`, `93.184.216.34` | tests | ✅ fixtures (TLD réservé, tests adverses SSRF) |
| `claude.ai` | tests OAuth | ✅ fixture CIMD |
| `git.company.internal`, `forge-mcp.example.com` | UI / .env.example | ✅ placeholders |
| `data.forgejo.org/forgejo/...` | compose, CI | ✅ registre officiel Forgejo |

**Aucun** domaine/IP tiers dans le code de production. Aucun endpoint d'exfiltration.

### Hooks, dépendances, CI, binaires

- `pyproject.toml` : build hatchling standard, aucun hook. `package.json` : pas de pre/postinstall.
- Dépendances toutes classiques (fastapi, httpx, sqlalchemy, mcp, cryptography, argon2-cffi…). `uv.lock` **100 % pypi.org** ; `package-lock.json` **100 % registry.npmjs.org**. Aucun typosquat, aucune URL git/tarball.
- `deploy/entrypoint.sh` : secrets copiés en 0400 vers un répertoire 0700 puis drop de privilèges `setpriv`. Pas de réseau, pas de `curl|sh`.
- CI : pas de `pull_request_target`, pas de secret utilisé, `permissions: contents: read`.
- Seul fichier non-texte tracké : `py.typed` (vide, PEP 561). `.pyc` et `frontend/dist` présents sur disque mais **non versionnés**.
- Aucune obfuscation : pas de blobs hex/base64, pas d'homoglyphes ; un seul `fetch` frontend, en `same-origin`.

### Provenance git

- `origin` désigne le fork de travail ; `upstream` = `github.com/kepatrick/forgejo-mcp.git` (auteur d'origine, release 2026-08-04).
- 6 commits locaux non poussés (OAuth 2.1 + durcissement) + **6 fichiers modifiés non commités** : rendent le paramètre RFC 8707 `resource` optionnel (résolu vers l'unique ressource configurée) + CORSMiddleware restreint. Conforme RFC, non malveillant — à relire avant commit.

> ℹ️ Constats info : actions GitHub épinglées par tag (`@v5`) et non par SHA ; artefacts locaux (`__pycache__`, `frontend/dist`) à nettoyer avant redistribution.

---

## 2. 🔴 Les deux failles HAUTES

### HAUTE №1 — Traversée par dot-segments : le grant d'outil ne borne plus l'endpoint

`_repository_name` (`client.py:2257-2266`) et `_ref_value` (`client.py:2232-2240`) acceptent `.` et `..` (seuls `/`, caractères de contrôle et longueur sont refusés). `quote(safe="")` ne les encode pas (`.` est « safe »), et **httpx 0.28.1 normalise les dot-segments avant l'envoi** — vérifié par exécution dans le venv du projet :

```
httpx.URL('https://h/api/v1/repos/o/r/git/commits/..') → https://h/api/v1/repos/o/r/git
```

**Scénario** : un token MCP n'ayant que `forgejo_get_repository` appelle l'outil avec `owner="..", repo="user"` → requête réelle `GET {base}/api/v1/user` (profil complet, e-mail inclus), endpoint que le modèle de permission réservait à `forgejo_get_current_user`. Idem `get_commit(sha="..")` → `GET .../repos/o/r/git`, `get_commit_status(ref="..")` → `GET .../repos/o/r/status`. La granularité des grants est contournée, et **l'audit journalise la cible fournie, pas l'URL atteinte**.

**Mitigations réelles** (bornent la sévérité) : même méthode HTTP, même PAT du même utilisateur (pas d'escalade de principal), parsing strict Pydantic des réponses qui casse l'exfiltration dans la plupart des cas, redirects refusés.

**⚠️ Réfute l'auto-audit du dépôt** : `security-audit-2026-08-31.md` affirme « Path traversal : no exploitable traversal found ; repository paths reject `..` » — la règle sur `..` n'existe que pour les chemins de *fichiers* (`_file_path`), pas pour owner/repo/refs. Contredit aussi `docs/security/organization-repository-creation.md:11` (« validated as one bounded path segment »).

**Correctif** (quelques lignes) : refuser `value in {".", ".."}` dans `_repository_name` et `_ref_value`, corriger le pattern `^[^/\x00-\x1f\x7f]+$` de `registry.py:89-90`, avec test témoin `owner=".."`.

### HAUTE №2 — Allowlist vide = exfiltration de PAT possible hors production

```python
# config.py:125-133
if not self.forgejo_allowed_base_urls:
    return True
```

`forgejo_credential_service.py:92-97` envoie le PAT en clair à `instance.base_url`. L'allowlist n'est obligatoire qu'en `environment=production` (`config.py:91-92`). **Scénario** : déploiement lancé hors compose en mode dev/staging exposé au réseau → un admin compromis (ou XSS/CSRF résiduel sur session admin) reconfigure l'instance vers un serveur qu'il contrôle ; au prochain `PUT /api/me/credential` ou `POST /test` de chaque utilisateur, leur PAT arrive en clair chez l'attaquant. C'est le scénario SEC-001 que le projet prétend avoir fermé — rouvert hors prod.

**Atténuations** : compose rend l'allowlist obligatoire (`:?set`), HTTP refusé par défaut. **Correctif** : refuser l'allowlist vide aussi hors production, ou au minimum warning bruyant au démarrage ; envisager de gater `verify_tls=false` derrière un flag de déploiement comme HTTP.

---

## 3. 🔐 Auth / OAuth 2.1 — remarquablement solide

### Points solides vérifiés dans le code

- **PKCE obligatoire, S256 uniquement** (`oauth_service.py:64,173`) ; **redirect_uri en exact-match** (enregistrement HTTPS/loopback seulement, re-comparée entre `/authorize` et `/token`) ; pas d'open redirect trouvé.
- **Codes à usage unique + anti-race** : `consumed_at` + `SELECT … FOR UPDATE` (`oauth_service.py:349-367`), TTL 60-600 s.
- **Rotation des refresh tokens + détection de replay** : toute réutilisation **révoque la famille entière** y compris les access tokens (`oauth_service.py:425-428`, `_revoke_family:620`).
- **Binding RFC 8707 partout** : autorisation, échange, refresh, bearer (`mcp_bearer.py:72`), avec `hmac.compare_digest`.
- Consentement : jeton opaque 256 bits haché, CSRF double (cookie `SameSite=strict` + Origin strict), HTML `escape()`é, **admins exclus du flux OAuth**.
- La migration `20260902_0009` supprime les tokens `kind='oauth'` au **downgrade** pour qu'ils ne redeviennent pas des bearers statiques — réflexe rare et excellent.
- **Tokens** : exclusivement `secrets.token_urlsafe(32)`, stockés **hachés SHA-256**, comparés `hmac.compare_digest` avec fail-closed si ≠ 1 candidat (`mcp_bearer.py:48-54`) ; révocation vérifiée à chaque authentification ET chaque décision d'outil ; contrainte DB `ck_mcp_tokens_enabled_lifecycle`.
- **Sessions** : cookies HttpOnly/Secure/`SameSite=strict`, pas de fixation (jetons régénérés au login), CSRF lié à la session (double-submit + hash), changement de mot de passe révoque les autres sessions.
- **Mots de passe** : Argon2id (défauts OWASP), **login à temps quasi constant** (verify contre hash factice si compte inexistant) — pas d'énumération par timing.
- **Élévation de privilèges : rien d'exploitable.** Bootstrap admin seulement si aucun admin, `must_change_password` bloquant partout ; invitations admin-only, rôle figé `USER`, usage unique sous `FOR UPDATE` ; **aucun endpoint orphelin** de dépendance auth ; **aucun IDOR** (toutes les ressources « me » scoped par user_id) ; grants token ⊆ allowance user, allowance modifiable par admin seul.

### Constats

| Sévérité | Constat | Emplacement |
|---|---|---|
| 🟠 MOYENNE | **Rate limiting keyé sur `request.client.host` sans gestion de proxy.** Derrière un reverse proxy (prod normale), toutes les requêtes partagent l'IP du proxy : (a) lockout DoS — clé login `ip:username` → n'importe qui verrouille n'importe quel username (5 échecs/5 min) ; (b) limites DCR (10/h) et invitations globales → DoS d'onboarding. À l'inverse, `--proxy-headers` sans allowlist rendrait `X-Forwarded-For` spoofable. | `api/auth.py:105-107`, `api/oauth.py:78,208`, `api/invitations.py:34-36` |
| 🟡→🟠 | Limiteurs en mémoire à croissance non bornée (`check()` crée une entrée par clé sondée, jamais purgée) + remise à zéro au restart, pas de lockout persistant | `auth/rate_limit.py:14-28,43` |
| 🟡 BASSE | Replay d'un code consommé ne révoque pas les tokens déjà émis (RFC 9700 le recommande) | `oauth_service.py:355-361` |
| 🟡 BASSE | Tokens MCP statiques perpétuels possibles (`expires_at` nullable) — TTL max configurable suggéré | `mcp_token_service.py:50` |
| 🟡 BASSE | Comparaison PKCE non constante (SDK MCP vendored ; exploitation impraticable) | SDK `handlers/token.py:178` |
| 🟡 BASSE | TOCTOU DNS (rebinding) sur le fetch CIMD, mitigé par allowlist admin | `oauth_service.py:720-744` |
| 🟡 BASSE | Politique de mot de passe = longueur ≥ 12 uniquement (pas de liste HIBP) | `auth/passwords.py:14-16` |
| 🟡 BASSE | Pas d'idle timeout de session ; `last_seen_at` figé au login (fraîcheur trompeuse dans `/api/auth/sessions`) | `auth/session.py`, `auth_service.py:61-69` |

---

## 4. 🔑 Crypto / credentials

### Points solides vérifiés ligne à ligne

- **AES-256-GCM** avec clé exigée à 32 octets exactement, **nonce 96 bits aléatoire par chiffrement** (`os.urandom`), **AAD liant ciphertext↔utilisateur↔version de clé** (`forgejo-credential:{user_id}:v{key_version}`) — empêche le rejeu inter-utilisateurs. **Aucune clé en dur, aucun fallback** : clé absente → `CredentialKeyError` → HTTP 503, **fail-closed**.
- **Le PAT n'est jamais renvoyé au client** (`CredentialResponse` = id/status/usernames/dates), l'admin ne peut que DELETE. Révocation = effacement cryptographique.
- Messages d'erreur du client Forgejo **statiques** (jamais d'écho d'URL/header/corps) ; `follow_redirects=False` empêche le rejeu du header Authorization vers un autre hôte.
- Aucun SECRET_KEY à défaut faible (pas de secret de signature : tout est aléa haché).
- Prod gardée : allowlist obligatoire, OAuth HTTPS obligatoire, cookies Secure, Swagger désactivé, pas de CORS `*`.
- Docker : secrets **exclusivement par fichiers montés ro**, Postgres publié sur `127.0.0.1` seulement, drop de privilèges.
- Logs : double filet clé+valeur (`logging.py:59-77`) — motifs `fmcp_…`, `Bearer/token …`, `://user:pass@` ; un dump accidentel de headers httpx serait redigé. Côté MCP, `_safe_error_message` réduit toute erreur à 4 messages génériques.

### Constats

| Sévérité | Constat | Emplacement |
|---|---|---|
| 🟠 MOYENNE | **Credential dans `clone_addr` persisté en clair dans l'audit AVANT rejet.** `record_decision()` (INSERT + commit de `redact_arguments(arguments)`) s'exécute avant la validation `_clone_address()` qui refuse `https://user:PAT@host/…` ; `redact_arguments` n'a pas de motif valeur `://[^@]+@` (contrairement au formateur de logs). L'appel échoue en 422 mais le token amont est écrit dans `tool_invocations.redacted_arguments` et resservi par l'API d'audit. Le test existant ne couvre qu'une URL **sans** credentials — témoin vert sur la mauvaise classe. | `mcp/server.py:182-196`, `tool_invocation_service.py:121-128`, `client.py:2115-2118` |
| 🟠 MOYENNE | **Contenus de fichiers commités archivés dans l'audit** (jusqu'à 4 Ko/champ pour `changes[].content`). Un `.env` ou une clé privée commis via `forgejo_commit_changes` finit dans la DB d'audit. Contraste : les *résultats* sont réduits à taille+SHA-256 — l'asymétrie arguments/résultats est le trou. | `audit/redaction.py:51-53` |
| 🟠 MOYENNE | `verify_tls: false` librement configurable par l'admin, sans flag de déploiement (HTTP clair en exige un) → MITM capture PAT + trafic | `api/forgejo_instance.py:16` |
| 🟠 MOYENNE | Images pinnées par tag mutable (`python:3.12-slim`, `postgres:16-alpine`…), pas par digest `@sha256:` | `deploy/Dockerfile`, `compose.yaml:70,88,107` |
| 🟡 BASSE | Rotation de clé mono-version : incrémenter la version rend tout indéchiffrable (piège opérationnel, honnêtement documenté) | `cipher.py:66-67` |
| 🟡 BASSE | Redaction par clé uniquement : `api_key`, `passwd`, `private_key` transparents (risque dormant retenu par le contenu actuel des schémas, pas par le code) | `audit/redaction.py:6-13` |
| 🟡 BASSE | Port applicatif publié sur toutes les interfaces (`0.0.0.0`) vs Postgres correctement borné ; `database_url` par défaut avec `change-me` ; bootstrap username `admin` par défaut | `compose.yaml:52`, `config.py:21` |

### Doctrine (`docs/security/credentials.md`) vs code

| Promesse | Verdict |
|---|---|
| AES-256-GCM, clé fichier, nonce neuf, AAD | ✅ conforme |
| Admin ne peut ni soumettre ni lire le PAT | ✅ |
| Révocation = effacement cryptographique | ✅ |
| « PATs jamais dans logs, audit, réponses API, exceptions » | ⚠️ **règle totale, implémentation partielle** : vrai pour le PAT du flux prévu, faux pour les secrets *amont* passés en arguments d'outil (constats ci-dessus) |

---

## 5. 🛠️ Couche outils / client Forgejo

### Points solides vérifiés

- **Le piège « sélecteur vérifié mais pas l'exécution » est évité** : la décision d'autorisation est **recalculée à chaque `tools/call`** (`mcp/server.py:176-193`), avant toute construction du service ; 6 couches fail-closed (`authorization/tools.py:20-32`) : token valide ∧ user actif ∧ outil activé globalement (**défaut = désactivé**) ∧ allowance user ∧ grant token ∧ credential actif. Outil inconnu → deny. Tests unitaires + intégration couvrent chaque couche.
- **Pas de confusion des députés** : PAT de l'utilisateur appelant exclusivement, lié par AAD, vérifié contre son identité Forgejo déclarée à l'enregistrement ; aucun argument d'outil ne peut désigner un credential/user/base URL.
- **Reçu d'audit écrit et COMMITTÉ avant l'appel Forgejo** (statut `PENDING` → `SUCCESS`/`FAILURE`) ; échec d'écriture du reçu = pas d'exécution (**fail-closed**) ; invocations refusées enregistrées (`DENIED` + raison) ; **API d'audit en lecture seule** (aucun endpoint de modification/suppression) ; champs dénormalisés robustes aux renommages.
- SSRF instance : URL admin-only, schémas http/https seulement (pas de `file://`), pas de credentials/query/fragment, allowlist **réappliquée à chaque appel porteur de PAT**, redirects = erreur.
- Entrées doublement bornées (schéma JSON + revalidation client) : pagination, tailles, listes, enums fermés, `additionalProperties: false` partout, timestamps RFC 3339 ; réponses bornées 10 Mo streamées et re-validées Pydantic `strict=True`.
- `/mcp` : Streamable HTTP uniquement, pile auth avant endpoint, rate limit par token ET par user, Origin allowlisté, CORS sans credentials, corps plafonné 2 Mo, drain coordonné au shutdown.

### Constats

| Sévérité | Constat | Emplacement |
|---|---|---|
| 🔴 HAUTE | Traversée dot-segments (détail en §2, HAUTE №1) | `client.py:2232-2266` |
| 🟠 MOYENNE | Conteneurs de référence en `0.0.0.0:8000` **sans TLS imposé** ; bearer MCP et cookies en clair si exposé sans reverse-proxy (documenté, non appliqué par le code) | `Dockerfile:31`, `compose.yaml:50` |
| 🟠 MOYENNE | `clone_addr` : garde anti-hôtes-privés **sans résolution DNS** — un nom public résolvant vers `169.254.169.254` passe ; rebinding non couvert. Nuance : la requête est exécutée par Forgejo, la garde est de la défense en profondeur devant les allowlists de Forgejo | `client.py:2104-2141` |
| 🟡 BASSE | `normalize_base_url` n'exclut pas les hôtes privés (admin-only, allowlist en prod ; dev/test = tout permis) | `client.py:104-126` |
| 🟡 BASSE | Décompression zip logs Actions : jusqu'à ~100×10 Mo de churn CPU depuis un Forgejo hostile | `client.py:1380-1402` |
| 🟡 BASSE | Colonne `forgejo_http_status` exposée par l'API d'audit mais **jamais renseignée** (surface qui annonce une donnée qu'aucun chemin ne produit) ; audit `target` = arguments fournis, pas l'URL effective ; crash post-appel = `PENDING` ambigu mais visible | `db/models.py:354` |
| ℹ️ Note | Contenus texte transmis tels quels à Forgejo (Markdown, workflows via `commit_changes`) — comportement attendu d'un client, responsabilité côté Forgejo | `client.py:943-992` |

---

## 6. 📋 Croisement avec l'auto-audit du dépôt (`security-audit-2026-08-31.md`)

| Revendication de l'auto-audit | Verdict de cet audit |
|---|---|
| SEC-001 (pin d'URL) « fixed » | ✅ en production ; ⚠️ **rouvert hors production** (allowlist vide = tout permis) — HAUTE №2 |
| SEC-002 (SSRF migration) « fixed » | ✅ garde présente ; ⚠️ sans résolution DNS (rebinding, nom public→IP interne) |
| SEC-003 (Origin `/mcp`) « fixed » | ✅ vérifié |
| SEC-004 (réponses bornées) « fixed » | ✅ vérifié (stream + cap 10 Mo) |
| SEC-005 (race invitations) « fixed » | ✅ vérifié (`FOR UPDATE`) |
| SEC-006 (redaction logs) « fixed » | ✅ côté logs ; ⚠️ l'audit d'invocations reste perméable (URL à credentials, contenus commités) |
| « Path traversal : no exploitable traversal found ; repository paths reject `..` » | ❌ **RÉFUTÉ** — vrai pour les chemins de fichiers seulement ; owner/repo/refs acceptent `..` (HAUTE №1) |
| « Permission bypass : no bypass found, fail-closed » | ✅ pour le modèle de grants lui-même ; ⚠️ la granularité est contournable par HAUTE №1 |
| « Secret storage : no defect » | ✅ vérifié |

---

## 7. ✅ Recommandations priorisées

1. **[HAUTE №1]** Refuser `{".", ".."}` dans `_repository_name` et `_ref_value` + corriger les patterns de schéma (`registry.py:89-90`). Correctif de quelques lignes, avec test témoin `owner=".."` (contrôle positif qui échoue avant, passe après).
2. **[HAUTE №2]** Refuser `permits_forgejo_base_url` à liste vide aussi hors production, ou au minimum warning bruyant au démarrage.
3. **[MOY. 4-5]** Ajouter un motif valeur `://[^@]+@` dans `redact_arguments` (aligné sur `logging.py:21`) et/ou valider `clone_addr` **avant** `record_decision` ; réduire `changes[].content` à taille+SHA-256 dans l'audit (comme `summarize_result` le fait déjà).
4. **[MOY. 3]** Gérer explicitement les proxys de confiance (`Forwarded`/allowlist) pour le rate limiting, ou documenter l'exposition directe comme contrainte dure.
5. **[MOY. 6-7]** Gater `verify_tls=false` derrière un flag de déploiement comme HTTP clair ; pinner les images par digest `@sha256:` ; imposer/documenter la terminaison TLS devant `0.0.0.0:8000`.
6. **[BASSES]** TTL max configurable pour les tokens MCP statiques ; purge des limiteurs en mémoire ; révocation des tokens émis sur replay de code OAuth ; renseigner ou supprimer `forgejo_http_status` ; étendre les fragments de redaction (`api_key`, `private_key`).

---

## Annexe — méthode

- 4 passes parallèles en lecture seule : malware/supply-chain (grep bruts, lockfiles, CI, git), auth/OAuth 2.1, crypto/credentials, couche outils/client.
- Comportement httpx (normalisation des dot-segments) **vérifié par exécution** dans le venv du projet, pas affirmé de mémoire.
- Doctrine documentée systématiquement confrontée au code réel (une docstring peut énoncer une règle totale que le code n'implémente qu'en partie).
- Aucun fichier du code modifié ; ce rapport est le seul fichier ajouté.
