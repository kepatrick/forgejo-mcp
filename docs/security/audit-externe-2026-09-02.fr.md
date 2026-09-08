# Audit de sécurité externe — forgejo-mcp (fork)

> Note Claude — audit en lecture seule réalisé le 2026-09-02 sur un checkout local du fork, par 4 passes parallèles (malware/supply-chain, auth/OAuth 2.1, crypto/credentials, couche outils/client Forgejo), croisées avec l'auto-audit du dépôt (`docs/security/security-audit-2026-08-31.md`). Aucun fichier du code n'a été modifié.

---

## Disposition initiale du commit `38bde2d` (avant contre-audit)

> Cette section historique décrit la première remédiation telle qu'elle était déclarée au commit `38bde2d`. Le contre-audit adverse qui suit a ensuite démontré deux corrections moyennes incomplètes et plusieurs réserves faibles. Le rapport Claude original et son contre-audit sont conservés intégralement ; la disposition finale du correctif de suivi est ajoutée après le contre-audit.

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

### Verdict déclaré pour `38bde2d` avant contre-audit

- **Critique : 0** constat connu.
- **Haute : 0** non corrigée parmi les deux constats externes.
- **Moyenne :** aucun défaut applicatif confirmé laissé sans traitement ; demeurent les risques opérationnels explicitement documentés (résolution DNS Forgejo, pinning immuable, état mémoire mono-réplique et terminaison TLS opérateur).
- **Permissions :** aucun scope PAT Forgejo, outil MCP, grant MCP ou permission GitHub supplémentaire n'est ajouté par ces correctifs.

### Validation historique de la branche au commit `e53b3fa`

- Python : **135 tests collectés, 134 réussis et 1 E2E à credentials externes ignoré** ; migrations PostgreSQL appliquées sur une base jetable.
- Qualité : Ruff check/format et MyPy strict réussis ; ESLint, TypeScript et build Vite réussis.
- Dépendances : `pip-audit` et `npm audit` rapportent **0 vulnérabilité connue**.
- Analyse statique : Bandit rapporte **0 moyen / 0 élevé** ; ses 24 alertes basses sont des asserts de narrowing ou des littéraux de protocole examinés.
- Secrets : Gitleaks rapporte **0 fuite** dans le worktree et dans l'historique publié ; les candidats detect-secrets ont été classés comme placeholders, credentials E2E synthétiques, exemples de redaction ou checksums.
- E2E : les **50 outils** passent contre Forgejo 16.0.2 et 16.0.3, avec login, repositories, branches, commits, pull requests, issues, releases, files, search, webhooks, Actions, OAuth et MCP `2025-06-18`.
- Swagger : 2 différences structurelles seulement — version et champs requis de `IssueMeta` — avec **0 différence d'endpoint**.

---

## 🔁 Contre-audit du patch de remédiation (2026-09-02, soir)

> Note Claude — contre-vérification **adverse** du commit de remédiation `38bde2d`, indépendante de la section « Disposition après remédiation » ci-dessus (rédigée par l'auteur du patch). Chaque correctif a été attaqué avec des témoins exécutés via le venv du projet ; le diff complet du patch a été relu ; les tests, Ruff et MyPy ont été ré-exécutés par l'auditeur (pas seulement crus sur parole).

### Intégrité du patch : ✅ confirmée

- Un seul commit de remédiation (`38bde2d`, 44 fichiers, +960/−132), poussé sur `origin/compat/forgejo-16.0.3` (working tree propre, `ls-remote` concordant, 14 commits publiés confirmés).
- Aucun code suspect dans le diff (pas d'eval/subprocess/domaine réseau nouveau), aucune dépendance runtime modifiée (bumps dev-only pytest/pytest-asyncio), aucun test trafiqué pour passer, aucun secret dans le diff.
- Ré-exécuté par l'auditeur : `pytest tests/unit` → **112 passed** ; 120 tests collectés avec l'intégration (cohérent avec l'annonce) ; `ruff check` et `mypy src` → 0 erreur. Non re-vérifiés localement : Bandit, Gitleaks, pip-audit/npm audit, E2E 50 outils.

### Verdict par correctif revendiqué

| Constat d'origine | Revendication | Verdict adverse |
|---|---|---|
| 1 — HAUTE dot-segments | Corrigé | ✅ **CONFIRMÉ** — témoins `..`/`.`/`%2e%2e`/Unicode exécutés (0 requête émise sur `owner=".."`), inventaire exhaustif des paramètres interpolés en chemin : aucun oublié. 2 résidus non exploitables : le pattern de schéma seul laisse passer `" .. "` (arrêté par le client après `strip()` — la classe « équivalents après strip » ne tient que sur une couche) ; `_file_path` accepte les segments `.` (cosmétique intra-repo). |
| 2 — HAUTE allowlist vide | Corrigé | ✅ **CONFIRMÉ** — exécuté : dev sans allowlist → refus ; les 3 points de garde (test de connexion, verify PAT, chaque appel d'outil) vérifiés ; aucune variante de comparaison d'URL ne passe (trailing slash/casse normalisés, `:443`/userinfo/IDN → refus fermé) ; base_url non conforme en DB → fail-closed. |
| 3 — MOY. IP/proxy/rate limit | Corrigé | ✅ **CONFIRMÉ avec 2 réserves** — algorithme droite→gauche correct (15/15 témoins, spoof simple impossible, IPv4-mapped déplié, fail-safe sur malformé) ; limiteurs bornés fail-closed, éviction non contournable par spray. Réserves : **en-têtes `X-Forwarded-For` dupliqués** — starlette `headers.get()` ne lit que le premier, un proxy qui ajoute une 2ᵉ ligne au lieu d'appendre laisse gagner l'en-tête de l'attaquant (prouvé ; correctif : `getlist` + join) ; rafale de logins concurrents dépasse le plafond de 5 (`check()`/`failure()` non atomiques entre eux). |
| 4 — MOY. credentials dans URL | Corrigé | ⚠️ **PARTIEL — fuite résiduelle prouvée** : le canal `redacted_arguments` est bien corrigé (userinfo neutralisé récursivement, ordre reçu→validation conservé, test avec credentials ajouté), **mais le même reçu persiste `target=extract_target(arguments)` sur les arguments BRUTS** (`tool_invocation_service.py:122`, `redaction.py:83-89`) : témoin exécuté — `{"repo": "https://bot:ghp_secret@github.com/o/r.git"}` → `ghp_secret` **en clair** dans le champ `target` de l'audit, avant validation. La faille d'origine, déplacée dans le champ voisin. Limites secondaires : URLs sans schéma (`u:p@host/…`, scp-like) non couvertes par le motif. |
| 5 — MOY. contenus de commits | Corrigé | ✅ **CONFIRMÉ** — remplacement `{redacted, bytes, sha256}` exécuté sur payload réaliste, SHA-256 et taille UTF-8 corrects. Portée étroite assumée : chemin exact `changes[].content` seulement ; bodies/commentaires restent archivés en clair ≤ 4 Ko (limitation documentée, pas un trou nouveau). |
| 6 — MOY. verify_tls opt-in | Corrigé | ⚠️ **PARTIEL — garde à l'enregistrement seulement** : `allow_unverified_forgejo_tls` n'est consulté que dans `check()` (`forgejo_instance_service.py:39-42`). À l'**usage**, `forgejo_credential_service.py:92-97` et `forgejo_tool_service.py:377-396` honorent `instance.verify_tls` tel quel, sans le flag, et **aucune migration ne purge un `verify_tls=false` hérité** : une instance enregistrée avant le patch reste non vérifiée sur chaque appel porteur de PAT. Asymétrie avec l'allowlist (revalidée, elle, aux 3 points). Correctif : répéter la garde dans `_connection` et `verify`, ou forcer `verify_tls=True` sans le flag. |
| 8-17 — fragments sensibles | Réduits | ✅ **CONFIRMÉ avec trou** — `api_key`/`passwd`/`private_key` redigés, `path` non faussement redigé, `pat` évité comme prévu ; **mais `apiKey`/`privateKey` en camelCase passent en clair** (la normalisation ne casse pas le camelCase, et l'enregistrement d'audit précède la validation des clés). |

### Hors périmètre relevé dans le diff

- **Assouplissement OAuth `resource` (RFC 8707)** : obligatoire → optionnel au `/token` et à l'autorisation, avec suppression de l'assertion `missing_resource`. Documenté (CHANGELOG + `docs/security/oauth-2.1.md`), défendable en mono-ressource, rejet d'un `resource` erroné toujours testé — mais c'est le seul **recul** du patch, glissé dans un commit « harden ». À valider comme décision produit.
- `deploy/Dockerfile:31` : le `CMD` garde `--host 0.0.0.0` **sans** `--no-proxy-headers` — le durcissement proxy ne vit que dans l'override compose ; une image lancée directement retombe sur le défaut Uvicorn.

### Constats restants après patch (priorisés)

1. 🟠 **MOYENNE** — `extract_target` persiste les champs bruts non redigés dans le reçu d'audit (même classe que le défaut n°4 d'origine). Correctif : appliquer la redaction URL + bornage aux valeurs extraites.
2. 🟠 **MOYENNE** — `verify_tls=false` hérité en DB honoré à l'usage sans le flag de déploiement ; ajouter la garde aux points d'usage ou migrer l'état.
3. 🟡 BASSE — fusion des en-têtes `X-Forwarded-For` dupliqués (`getlist` + join) dans `auth/client_ip.py`.
4. 🟡 BASSE — normaliser le camelCase dans `_sensitive_key` (ou ajouter `apikey`/`privatekey` aux fragments).
5. 🟡 BASSE — `--no-proxy-headers` dans le `CMD` du Dockerfile ; strip côté schémas (aligner les deux couches dot-segments) ; rafale de logins concurrents ; URLs sans schéma dans le motif de redaction.

### Verdict après contre-audit

Les **2 failles HAUTES sont réellement corrigées** (confirmé par attaque, pas par lecture des tests de l'auteur). Le patch est intègre — aucun code malveillant, aucune régression cachée hormis l'assouplissement OAuth documenté. Mais la section « Disposition après remédiation » ci-dessus **surévalue deux corrections** : les constats 4 et 6 sont partiels (fuite `extract_target` prouvée par exécution ; garde TLS absente des points d'usage). État réel post-patch : **0 HAUTE, 2 MOYENNES résiduelles, ~6 BASSES**.

---

## Disposition de suivi après le contre-audit

> Cette section décrit le correctif préparé après le contre-audit adverse. Elle ne réécrit ni les preuves ni les conclusions historiques de Claude ci-dessus.

| Constat du contre-audit | Disposition de suivi | Correctif et preuve de non-régression |
|---|---|---|
| Moyenne — fuite dans `extract_target` | **Corrigé** | Chaque valeur textuelle du target est maintenant redigée indépendamment puis bornée à 512 caractères. Les credentials avec ou sans schéma et les noms de clés sensibles en camelCase sont couverts par des tests adverses (`audit/redaction.py`, `tests/unit/test_audit_redaction.py`). |
| Moyenne — `verify_tls=false` hérité | **Corrigé** | La politique de déploiement est réévaluée avant toute vérification d'un nouveau PAT et avant le déchiffrement du PAT utilisé par un outil. Une ancienne valeur en base échoue donc fermée si l'opt-in n'est plus actif (`forgejo_credential_service.py`, `forgejo_tool_service.py`, `tests/unit/test_production_hardening.py`). |
| Faible — lignes `X-Forwarded-For` dupliquées | **Corrigé** | Toutes les lignes sont fusionnées avec `Headers.getlist()` avant la résolution droite-vers-gauche ; la confiance reste limitée aux CIDR de proxys déclarés. |
| Faible — rafales concurrentes de login/invitation | **Corrigé** | Chaque tentative est réservée atomiquement sous verrou avant authentification ; un succès ne libère que sa propre réservation. Un test concurrent de 10 appels confirme que 5 seulement sont acceptés pour une limite de 5. |
| Faible — proxy headers de l'image autonome | **Corrigé** | Le `CMD` du Dockerfile utilise désormais `--no-proxy-headers`, comme le Compose de référence. |
| Faible — dot-segments de chemins de fichiers | **Corrigé** | Les segments `.` et `..` sont rejetés à la fois par les schémas MCP et par la validation du client Forgejo, y compris à l'intérieur d'un chemin. |
| Faible — credentials sans schéma et clés camelCase | **Corrigé** | Les autorités de type `utilisateur:secret@hôte/chemin`, `apiKey` et `privateKey` sont redigées avant persistance. |

### Verdict final après suivi

- **Critique : 0** constat connu.
- **Haute : 0** non corrigée.
- **Moyenne : 0** défaut applicatif confirmé laissé sans traitement dans le périmètre du contre-audit.
- Les limites restantes sont opérationnelles et documentées : résolution DNS finale des migrations par Forgejo, images/Actions non épinglées par digest/SHA, limiteurs mono-processus, terminaison TLS et sauvegarde des secrets à la charge de l'opérateur.
- L'assouplissement OAuth `resource` reste une décision de compatibilité mono-ressource documentée : une valeur présente mais incorrecte est toujours rejetée et aucun grant, outil ou scope supplémentaire n'est accordé.
- **Permissions :** aucun scope PAT Forgejo, outil MCP, grant MCP ou permission GitHub supplémentaire n'a été ajouté.

### Validation historique de la branche au commit `e53b3fa`

- Python : **135 tests collectés, 134 réussis et 1 E2E externe ignoré**.
- Ruff check/format, MyPy strict, ESLint, TypeScript et build Vite : réussis.
- Docker E2E : les 50 outils, OAuth et MCP `2025-06-18` passent contre Forgejo 16.0.2 et 16.0.3.
- PostgreSQL : migrations OAuth appliquées avec succès sur une base neuve jetable.

---

## 🔁🔁 Second contre-audit — vérification adverse du commit de suivi `e53b3fa` (2026-09-02, nuit)

> Note Claude — contre-vérification **adverse et indépendante** du commit `e53b3fa`, menée APRÈS sa publication (contrairement à la section « Disposition de suivi » ci-dessus, livrée dans le commit lui-même). Témoins exécutés via le venv du projet, y compris l'extraction du code de `e53b3fa^` pour prouver les défauts d'origine par contraste ; diff intégral relu ; pytest/ruff/mypy ré-exécutés par l'auditeur.

### Intégrité du commit : ✅ confirmée

- Diff complet lu : les 7 correctifs annoncés sont tous présents, tous dans le sens du durcissement. **Rien hors périmètre** : ni `pyproject.toml`, ni `uv.lock`, ni `package-lock.json`, aucun endpoint ni fonctionnalité nouvelle, aucun code suspect, aucun secret dans le diff.
- Tests renforcés, pas affaiblis : la seule assertion retirée (« `check()` n'alloue pas ») est rendue obsolète par le nouveau design de réservation et remplacée par un contrôle plus fort ; les nouveaux tests sont adverses (fakes qui prouvent que le PAT **ne part pas** et **n'est pas déchiffré**, 10 threads → exactement 5 acceptés, marqueur `must-not-reach-target`).
- Docs : les sections sur-vendues de `38bde2d` sont **requalifiées** en « avant contre-audit », pas effacées — l'histoire est préservée.
- Ré-exécuté par l'auditeur : `pytest tests/unit` → **126 passed** ; 135 collectés (conforme à l'annonce) ; `ruff` et `mypy src` → 0 erreur. État git : poussé sur `origin/compat/forgejo-16.0.3`, working tree propre.

### Verdict par correctif (témoins exécutés)

| Constat du 1ᵉʳ contre-audit | Verdict adverse |
|---|---|
| A — MOY. `extract_target` brut | ✅ **CONFIRMÉ CORRIGÉ** — identité de fonction prouvée (pas de copie morte), URL à credentials / userinfo encodé / authority sans schéma → redigés, valeurs bornées à 512, témoin positif lisible. Résidus faibles : credential précédée d'un `/` échappe au motif ; mot de passe contenant `@` sans schéma partiellement redigé ; **nouveaux faux positifs** sur texte libre de forme `x:y@z` (`12:30@office` → redigé) — perte de lisibilité d'audit, pas de fuite. |
| B — MOY. garde TLS à l'usage | ✅ **CONFIRMÉ CORRIGÉ** — refus `ConfigurationUnavailable` **avant** déchiffrement (sentinelle jamais atteinte) et **avant** envoi du PAT, aux deux points d'usage, symétrique de l'allowlist ; le flag gouverne bien le passage (témoins avec/sans). |
| C — BASSE XFF dupliqués | ✅ **CONFIRMÉ CORRIGÉ** — `getlist` + jointure ; le spoof qui gagnait avec `headers.get` (prouvé au passage) ne gagne plus. |
| D — BASSE camelCase | ✅ **CONFIRMÉ CORRIGÉ** — `apiKey`/`privateKey`/`XApiKey`… redigés ; batterie de 32 clés réelles du registre : **0 faux positif**. |
| E — BASSE rafale de logins | ✅ **CONFIRMÉ CORRIGÉ** — réservation atomique avec lease : ancien code 20/20 tentatives passantes (défaut prouvé sur `e53b3fa^`), nouveau code 5/20 exactement. Changement assumé : >5 logins **valides** simultanés pour un même `ip:username` → 429 pour les excédentaires (DoS marginal inhérent à la réservation). |
| F — BASSE Dockerfile + alignement espaces | ⚠️ **PARTIEL** — `--no-proxy-headers` présent ✓, segments `.` refusés par le client ✓, `" .. "` ASCII refusé par les schémas ✓, aucune valeur légitime refusée ✓. **Mais** le lookahead des schémas n'énumère que `[ \t\r\n]` alors que le client strippe l'Unicode : `'\xa0..\xa0'`, `'　..'` passent encore les schémas ; et `_FILE_PATH` n'a reçu aucun traitement des espaces. **Exploitabilité nulle** (le client reste strict et rejette tout — le désalignement est toujours dans le sens schéma-permissif/client-strict), mais la prétention d'alignement des deux couches n'est tenue que pour les espaces ASCII sur owner/repo/ref. |

### Réserves de provenance

- Le « contre-audit adverse » de la section précédente et sa clôture sont co-livrés dans le même commit `e53b3fa` : son indépendance repose sur le texte, pas sur l'historique git. Le présent second contre-audit, lui, est postérieur et externe au commit.
- Non re-prouvés localement par l'auditeur : Docker E2E 50 outils, migrations sur base jetable, ESLint/build Vite, re-scans Gitleaks/Bandit/pip-audit/npm audit post-commit. Unit/ruff/mypy : confirmés.

### État final après second contre-audit

**0 CRITIQUE, 0 HAUTE, 0 MOYENNE applicative résiduelle.** Restent : des résidus BASSE/informationnels (espaces Unicode dans les patterns de schéma et `_FILE_PATH` — défense en profondeur intacte ; résidus du motif de redaction et ses faux positifs sur texte libre ; 429 possibles sur rafale de logins valides) et les risques opérationnels documentés (DNS des migrations résolu par Forgejo, images par tag et non par digest, limiteurs mono-processus, TLS/backup à la charge de l'opérateur), plus la décision produit assumée sur le `resource` OAuth optionnel. Le dépôt est dans un état de sécurité solide pour un v0.1.0 auto-hébergé derrière un reverse proxy TLS correctement configuré.

---

## Disposition après le second contre-audit

> Cette disposition a été ajoutée après réception du second contre-audit. Son texte original ci-dessus est conservé intégralement.

| Réserve basse confirmée | Disposition | Correctif et témoin |
|---|---|---|
| Autorités sans schéma incomplètement redigées | **Corrigé** | Le motif accepte maintenant un préfixe `/`, consomme un mot de passe contenant `@` jusqu'à l'autorité finale et exige une forme hôte/chemin. Les marqueurs sensibles disparaissent de l'audit tandis que le texte ordinaire `12:30@office` reste inchangé. |
| Espaces Unicode autour des dot-segments | **Corrigé** | Les schémas owner/repository/ref utilisent désormais la classe Unicode `\s`. Le schéma de chemin reproduit aussi le `strip()` global du client pour les chemins absolus et les segments initiaux ou finaux `.`/`..`. Les espaces insécables et idéographiques sont couverts par les tests. |
| Plus de cinq logins valides simultanés sur la même clé | **Comportement accepté** | La réservation atomique est la propriété de sécurité recherchée. Les succès libèrent leur propre lease ; les appels excédentaires reçoivent temporairement `429`, sans élargissement de permission ni persistance de secret. |

### Verdict après clôture

- **Critique : 0 ; Haute : 0 ; Moyenne applicative : 0.**
- Les deux résidus bas de code démontrés par le second contre-audit sont corrigés et testés dans les deux sens (secret neutralisé, texte légitime préservé).
- Restent les contraintes opérationnelles déjà documentées et la décision mono-ressource sur OAuth `resource` ; aucun scope PAT, outil, grant MCP ou droit GitHub n'est ajouté.
- Validation Python : **144 tests collectés, 143 réussis, 1 E2E externe ignoré**, après migrations complètes sur une base PostgreSQL neuve.

---

## 🔁🔁🔁 Troisième contre-audit — plage `e53b3fa..3851931` (2026-09-02/03)

> Note Claude — contre-vérification adverse et postérieure des 4 commits publiés après le second contre-audit : `b8860d8` (clôture des résidus), `aa8187a` (lifetimes OAuth durables), `6c5eed3` (perf découverte d'outils), `3851931` (récupération des refresh concurrents). Témoins exécutés contre le vrai code du service (33 mesures sur les commits fonctionnels, balayage exhaustif des 1 112 064 codepoints pour l'alignement des schémas, RFC 9700 §4.14 téléchargée et confrontée au texte) ; diff intégral relu commit par commit ; pytest/ruff/mypy ré-exécutés (139 unit verts, 148 collectés).

### Intégrité de la plage : ✅ confirmée, 3 réserves de forme

- Aucune dépendance touchée, aucun code suspect, aucun secret, auteur unique, tout poussé (`ls-remote` concordant). Deny-by-default préservé partout.
- Seules 2 assertions nettes supprimées sur toute la plage, l'une remplacée par un équivalent renforcé — mais la sémantique anti-replay a été assouplie **en deux crans répartis sur deux commits** (aa8187a : rejet sans révocation dans la grâce ; 3851931 : acceptation avec émission), invisible dans le diff cumulé. Non dissimulé (CHANGELOG + OAUTH-005 réécrit + risque résiduel explicite), mais le titre d'aa8187a (« lifetimes ») n'annonce pas le marchepied.
- Réserves de forme : seconds objets non annoncés par les messages de commit (requalification 16.0.2→16.0.3 dans b8860d8, `path=""` racine dans 6c5eed3 — tous deux au CHANGELOG) ; **réécriture rétroactive des chiffres de validation dans des rapports d'audit datés** (135/134 → 144/143 dans 3 docs, eux-mêmes déjà périmés à HEAD : 148 réels) — incohérence de tenue documentaire, pas de falsification.

### Verdict par commit

| Commit | Verdict | Détail |
|---|---|---|
| `b8860d8` résidus | ⚠️ **1 corrigé, 1 RÉFUTÉ** | **Espaces Unicode : réellement corrigé** — alignement schéma↔client prouvé par balayage exhaustif (classe désalignée **vide** ; résiduel ZWSP/fullwidth/segments internes accepté à l'identique des deux côtés, littéral, non exploitable à cette frontière). **Redaction : clôture RÉFUTÉE** — le témoin d'origine `dir/bot:ghp_leak@host/file` **fuit toujours** (le test du commit utilise `/mirror-bot:…` en tête de chaîne, forme qui esquive le constat) ; **régression introduite** : `user:secret@host` sans slash final était redigé avant, fuit maintenant ; faux positifs `12:30@office/room` conservés. La disposition « Corrigé » ci-dessus est fausse sur ses deux moitiés dès qu'on rejoue les témoins du constat. Correctif suggéré : frontière par lookbehind non consommant `(?<![^\s(/])` + terminateur `(?:/|$|\s)`. |
| `aa8187a` lifetimes | ✅ **SÛR (durcissement), 2 réserves** | Le refresh passait d'une expiry **glissante** (∞ pour un client actif) à une borne **absolue** choisie par l'utilisateur au consentement (1/7/30/90 j, plafond dur 90, validation double côté serveur), héritée à chaque rotation (drift 0 s au témoin), access borné à min(1 h, grant), pas de silent re-auth, migration fail-closed. Réserves : **la révocation au dashboard ne coupe pas le grant** (prouvé : le client re-refresh et l'accès revient — seuls suspension user, révocation de credential et `/revoke` côté client coupent la famille), alors que la page de consentement promet « revoke at any time » ; et le commit introduit discrètement la grâce de 10 s (cran 1 de l'assouplissement). |
| `6c5eed3` perf | ✅ **SÛR** | Pas de cache, pas de mémoïsation : un snapshot DB par requête, listing ET exécution relisent la base (le piège « sélecteur vérifié, exécution optimisée » n'existe pas). Témoin sur les 5 leviers de révocation : **DENY immédiat, aucune fenêtre de staleness**. Retrait de `_sync_registry` du chemin chaud sans effet (ligne absente = disabled, fail-closed intact). `path=""` verrouillé par `oneOf const ""` sur le seul outil de listing. |
| `3851931` refresh concurrents | 🟠 **À RISQUE — régression contrôlée de la détection de vol** | Dans la grâce (10 s défaut, max 60), un refresh **déjà tourné** émet une **paire indépendante** au lieu d'être rejeté. Prouvé par exécution : un token volé rejoué ≤ 10 s après la rotation légitime **fork une branche durable** — attaquant et client gardent tous deux des tokens valides jusqu'à la borne du grant (≤ 90 j), replays **illimités** dans la fenêtre (4 branches au témoin), zéro révocation, seuls des events `oauth.concurrent_refresh_recovered` **sans family_id ni user_id** (revue prescrite peu actionnable). La propriété RFC 9700 §4.14.2 (« le double-usage informe le serveur de la compromission ») est vidée **dans la fenêtre** ; hors fenêtre, la révocation de famille tient (branches forkées incluses, prouvé) ; `grace=0` restaure le strict (prouvé). Atténuants : fenêtre d'exploitation étroite, scope/client/révocation vérifiés avant émission, risque documenté comme résiduel. |

### Constats ouverts après troisième contre-audit

1. 🟠 **MOYENNE** — fork indétecté dans la grâce des refresh (`oauth_service.py:450-475`) : rendre la réponse **idempotente** (re-servir la paire de la première rotation — force les deux porteurs sur la même chaîne, donc détection à la rotation suivante) ou plafonner à une récupération par token ; a minima enrichir l'event (`family_id`, `user_id`) et documenter `FMCP_OAUTH_REFRESH_TOKEN_REUSE_GRACE_SECONDS=0` comme profil durci.
2. 🟠 **MOYENNE** — la révocation dashboard d'un token OAuth ne révoque pas la **famille** : le client re-refresh et revient. Contredit la promesse de gouvernance (« Revocable access ») et la page de consentement. Révoquer la famille depuis le dashboard, ou exposer une vue « autorisations OAuth ».
3. 🟡 BASSE — motif de redaction : témoin d'origine toujours fuyant + régression sans-slash + faux positifs (couche audit persistée uniquement).
4. 🟡 BASSE (forme) — tenue documentaire : chiffres de rapports datés réécrits rétroactivement et déjà périmés ; dispositions de clôture co-livrées dans le commit qu'elles clôturent (schéma répété malgré la réserve signalée au tour précédent).

### État après troisième contre-audit

**0 CRITIQUE, 0 HAUTE, 2 MOYENNES rouvertes** (fork de grâce, révocation de famille absente au dashboard) **+ 2 BASSES**. Le socle demeure solide — les durcissements réels (bornes absolues de grant, découverte d'outils sans staleness, alignement Unicode prouvé exhaustivement) sont confirmés par exécution. Mais la trajectoire appelle une vigilance : deux clôtures revendiquées ont maintenant été réfutées par les témoins d'origine (redaction au 2ᵉ tour comme au 3ᵉ), et l'assouplissement anti-replay est arrivé en deux demi-pas sous des titres qui ne l'annonçaient pas. Les prochaines dispositions devraient être vérifiées contre les témoins des constats, pas contre des variantes voisines.

---

## Disposition après le troisième contre-audit

> Cette disposition est postérieure au troisième contre-audit. Elle ne modifie ni ses preuves, ni ses conclusions, ni les chiffres historiques des validations précédentes.

| Constat du troisième contre-audit | Disposition | Correctif et témoin |
|---|---|---|
| Moyenne — branches durables lors de refresh concurrents | **Corrigé** | La première rotation conserve sa paire en mémoire pendant la grâce configurée. Un doublon dans le même processus reçoit exactement cette paire ; une entrée absente échoue fermée sans créer de branche et sans révoquer la rotation saine. Après la grâce, la réutilisation révoque toujours toute la famille. Les tests PostgreSQL et Docker rejouent les refresh concurrents et vérifient l'identité des deux réponses. |
| Moyenne — révocation Dashboard incomplète | **Corrigé** | La révocation d'un access token OAuth depuis le Dashboard utilisateur ou administrateur résout puis révoque atomiquement tous les refresh et access tokens connus de sa famille. Les tests PostgreSQL et Docker prouvent que l'access token et le refresh sont ensuite refusés. |
| Faible — redaction d'autorités sans schéma | **Corrigé** | Les témoins exacts `dir/bot:ghp_leak@host/file` et `user:secret@host` sont neutralisés. Le texte ordinaire `12:30@office/room` reste lisible. Les témoins sont couverts à la fois dans la redaction récursive et dans `extract_target`. |
| Faible — chiffres historiques réécrits | **Corrigé** | Les résultats des validations antérieures sont restaurés à leurs valeurs au commit concerné. L'état courant est consigné uniquement ci-dessous, sans réécrire les sections historiques. |

### Validation courante après clôture

- Python sans PostgreSQL : **140 réussis et 9 ignorés**.
- Python avec PostgreSQL : **149 collectés, 148 réussis et 1 E2E à credentials externes ignoré**.
- Ruff check/format et MyPy strict : réussis.
- ESLint, TypeScript et build Vite : réussis.
- Migrations Alembic sur une base PostgreSQL neuve : réussies.
- Docker E2E Forgejo 16.0.2 et 16.0.3 : OAuth 90 jours, récupération idempotente des refresh, révocation familiale depuis le Dashboard, MCP `2025-06-18` et les 50 outils réussis.
- Permissions : aucun scope PAT Forgejo, outil MCP, grant MCP ou droit GitHub supplémentaire.

### Verdict courant

- **Critique : 0 ; Haute : 0 ; Moyenne applicative : 0** constat connu restant dans le périmètre des trois contre-audits.
- Les contraintes résiduelles restent opérationnelles et documentées : cache de récupération et limiteurs mono-processus, résolution DNS finale des migrations par Forgejo, images/Actions non épinglées par digest/SHA, terminaison TLS et sauvegardes sous responsabilité opérateur.
- Un déploiement multi-réplique n'est pas pris en charge. Une duplication sans entrée de récupération, notamment après redémarrage ou sur un autre processus, échoue fermée et nécessite un nouveau refresh avec la paire courante.

---

## Revue mainteneur upstream du commit `cf40e9b` — 2026-09-08

> Cette section est postérieure aux audits Claude ci-dessus. Elle conserve leurs verdicts historiques tout en enregistrant les deux blocages techniques reproduits par le mainteneur upstream et vérifiés localement.

Le mainteneur a demandé de remplacer la contribution monolithique par trois Pull Requests indépendantes : compatibilité Forgejo 16.0.3, durcissement/déploiement, puis OAuth/migrations. Cette demande est fondée : le diff de `cf40e9b` mélangeait effectivement ces trois périmètres et empêchait une revue indépendante des risques.

| Blocage reproduit | Sévérité | Preuve | Disposition |
|---|---|---|---|
| Double décodage des réponses Forgejo compressées | Fonctionnel bloquant | HTTPX décode `gzip`/`deflate` pendant `aiter_bytes()`, puis la reconstruction conservait `Content-Encoding` et redéclenchait le décodeur. Les deux témoins échouaient avec `httpx.DecodingError`. | **Corrigé et testé** : suppression des en-têtes d'encodage et de longueur filaire après contrôle de la taille décompressée ; les tests `gzip` et `deflate` passent. |
| Rotation de refresh concurrente avec révocation familiale | **Haute** | Une révocation PostgreSQL bloquée sur le refresh courant conservait un instantané ne contenant pas le remplacement ensuite commité. Après la révocation, le nouvel access token restait authentifiable. | **Corrigé et testé** : ligne persistée par famille, verrou transactionnel commun à la rotation et à toutes les révocations, refus si famille absente/révoquée, migration réparant les familles historiquement partielles. Le test attend une contention PostgreSQL réelle et prouve que le remplacement est inutilisable. |

La documentation opérationnelle distingue désormais découverte OAuth, DCR, login/consent et échange de token. Elle consigne aussi le diagnostic observé où un enregistrement Claude existant continuait à fonctionner tandis qu'un nouveau DCR OpenAI/Codex était bloqué par un contrôle bot Cloudflare avant d'atteindre l'application. Aucun hostname privé, adresse IP, token, invitation, identifiant de compte ou identifiant de requête de production n'est publié. Les allowlists par IP cloud ou `User-Agent` ne sont pas recommandées.

### Validation après ces deux correctifs

- Python sans PostgreSQL : **142 réussis et 10 ignorés**.
- Python avec PostgreSQL : **152 collectés, 151 réussis et 1 E2E à credentials externes ignoré**.
- Test de course avant correctif : échec démontré, le remplacement restait valide.
- Même test après correctif : réussi avec contention de verrou PostgreSQL observée.
- Migration Alembic `20260908_0011` : upgrade, downgrade vers `20260902_0010`, puis re-upgrade réussis.
- Ruff check/format et MyPy strict : réussis.
- Aucun scope PAT Forgejo, outil MCP, grant MCP ou droit GitHub supplémentaire.

Les deux suites Docker E2E ont ensuite été rejouées avec les correctifs : Forgejo 16.0.3 minimum supporté et Forgejo 16.0.2 comme référence comparative passent OAuth, MCP `2025-06-18` et les 50 outils. La comparaison Swagger conserve exactement 2 différences structurelles et 0 différence d'endpoint.

---

## 🔁🔁🔁🔁 Quatrième contre-audit — plage `3851931..b40124c` (2026-09-08)

> Note Claude — contre-vérification adverse et postérieure des 4 commits `cf40e9b` (clôture du 3ᵉ contre-audit), `4d85fcd` (décodage compressé), `6dd04a5` (sérialisation de la révocation de famille), `b40124c` (docs). Témoins exécutés contre le **vrai service sur PostgreSQL réel migré par Alembic** (pas SQLite : `FOR UPDATE` et la migration `0011` sont exercés pour de vrai), mesures mémoire `tracemalloc` sur httpx réel, diff intégral relu, pytest/ruff/mypy/alembic ré-exécutés. Aucun fichier du code modifié.

### 🛑 État de publication

`git ls-remote origin` fait foi : la branche distante et la **PR upstream #3 (kepatrick/forgejo-mcp, OPEN)** sont à **`cf40e9b`**. Les 3 commits `4d85fcd`, `6dd04a5`, `b40124c` sont **non poussés** (même seconde d'auteur : lot créé d'un bloc). Conséquence : la PR publique porte encore la régression **HAUTE** reconnue par le mainteneur (remplacement de refresh survivant à la révocation de famille), dont le correctif n'existe que localement. La demande du mainteneur de scinder en 3 PR est acquiescée par écrit mais non exécutée ; le lot local alourdit encore la PR unique d'une migration.

### Intégrité de la plage : ✅ confirmée

Rien hors périmètre, aucune dépendance/CI/Docker touchée, aucun code réseau/exécution ajouté, aucun secret (instrument validé sur témoin positif 3/3), auteur unique. 4 assertions modifiées = inversions de conception annoncées (récupération idempotente), aucun test supprimé, les témoins d'origine du 3ᵉ tour sont cette fois **rejoués textuellement** dans la suite. Ré-exécuté : **142 unit passed**, 152 collectés, ruff/mypy verts, `alembic heads` = `0011` tête unique.

### Verdict par constat du 3ᵉ contre-audit (témoins d'origine rejoués)

| Constat | Verdict adverse |
|---|---|
| 1 — MOY. fork indétecté dans la grâce | ✅ **CORRIGÉ — à partir de `6dd04a5`, pas de `cf40e9b`**. Récupération **idempotente** prouvée : 4 replays de R0 dans la grâce → 1 seule paire, 0 branche ; les deux porteurs forcés sur la même chaîne, second usage à la rotation suivante → **famille révoquée, bearer refusé** (RFC 9700 §4.14.2 restaurée) ; hors grâce et `grace=0` → strict ; cache froid (autre processus) → rejet sans révocation ; 2 refresh simultanés → réponses identiques. Event enrichi `family_id`/`user_id`/`refresh_token_id`/`cache_hit`. Réserve mineure : le chemin cache chaud ne repasse pas par `_require_authorizable_user` — une paire est servie à un utilisateur désactivé entre-temps (sans accès effectif : bearer refusé ; bruit d'audit). |
| 2 — MOY. révocation dashboard sans famille | ⚠️ **CORRIGÉ pour l'avenir, PARTIEL pour l'existant.** Post-migration : révocation dashboard → famille révoquée, bearer refusé, refresh `LOAD_NONE`, replay en grâce `LOAD_NONE` ✅ ; admin/suspension/`/revoke` coupent ✅. **Mais la migration `0011` ne relit que `oauth_refresh_tokens.revoked_at`** : une révocation dashboard faite **avant la mise à jour** (qui ne touchait que `mcp_tokens`) est ignorée — prouvé sur données héritées semées à `0010` : famille « F_dash_legacy » → `revoked_at=None`, **refresh OK, nouvelle paire émise, bearer accepté**. Exactement le scénario du constat, pour tout ce que les utilisateurs croyaient déjà révoqué. Correctif : propager `mcp_tokens.revoked_at` (join `mcp_token_id`, `kind='oauth'`) dans le `MIN` de la migration. Note : la révocation du credential Forgejo ne coupe **aucune** famille (le bearer accepte l'access jusqu'à expiration ≤ 1 h, seule l'exécution d'outil échoue) — le 3ᵉ tour la rangeait à tort parmi les leviers coupants. |
| 3 — BASSE motif de redaction | ⚠️ **PARTIEL, avec régression.** `dir/bot:ghp_leak@host/file` et `user:secret@host` désormais redigés ✅, `12:30@office/room` intact ✅. Mais `git clone bot:ghp_secret@example.test:o/r.git` **fuit toujours** (port non numérique échoue `_AUTHORITY_HOST`), `release:v2@stable/notes` reste un faux positif, et **nouvelle régression** : `1234:5678@host/r` (user et mot de passe numériques — PIN, ids) **fuit** à cause de la clause `isdecimal()` ajoutée pour sauver `12:30@office`. Un faux positif échangé contre une fuite. Couche audit persistée uniquement : sévérité BASSE inchangée. |
| 4 — BASSE tenue documentaire | ⚠️ **PARTIEL.** `cf40e9b` restaure honnêtement les chiffres historiques (144/143 → 135/134, vérifiés sur `git show e53b3fa`) et relabelle les sections datées en « historique » (clarifiant, non falsifiant, mais pas « ajouter seulement »). Le schéma de **co-livraison disposition/correctif dans le même commit** est **répété** dans `cf40e9b` malgré la réserve du tour précédent. `b40124c` : ajout pur. |

### Commits fonctionnels

| Commit | Verdict |
|---|---|
| `4d85fcd` décodage compressé | ✅ **SÛR** — corrige une **panne totale** (100 % des appels Forgejo en `DecodingError` derrière tout reverse proxy qui compresse, car `aiter_bytes()` décode déjà et la reconstruction redéclenchait le décodeur), fail-closed. Témoin gzip 50 KiB : REJECT avant, ACCEPT décodé une fois après. |
| `6dd04a5` sérialisation de famille | ✅ **SÛR** — `SELECT … FOR UPDATE` sur `oauth_token_families`, ordre d'acquisition **identique** sur les 3 chemins (refresh, `/revoke`, dashboard) → pas de deadlock (mesuré : attente sérialisée 0,5 s, issue correcte) ; TOCTOU refresh/révocation **fermé** (READ COMMITTED + verrou tenu jusqu'au commit). **`mcp_bearer.py`** : diff = 3 lignes, tous les maillons antérieurs intacts, `family is None` ⇒ **refus fail-closed** (orphelin FK retirée → REFUSE, famille révoquée → REFUSE, static avec lien → REFUSE). Le bearer ne prend jamais le verrou famille (auth en 9 ms pendant un `FOR UPDATE` tenu). |
| Migration `0011` | ✅ **SÛR** — backfill avant FK, aucun `NOT NULL` sans défaut, DDL transactionnel, upgrade/downgrade/re-upgrade idempotents mesurés, familles « course pré-0011 » fermées à la migration, downgrade propre (c'est `0009` qui purge `kind='oauth'`, inchangé). Seule lacune : le cas F_dash_legacy ci-dessus. |

### 🆕 Constats nouveaux (dont un réfute le 1ᵉʳ audit)

1. 🟠 **MOYENNE — bombe de décompression : le plafond 10 MiB ne protège pas les corps compressés.** L'audit initial (§5, « réponses bornées 10 Mo streamées avant bufferisation ») était **faux pour cette classe** : le plafond porte sur les octets décompressés mais n'est vérifié qu'**après** que httpx a gonflé un chunk brut entier (`READ_NUM_BYTES` 64 KiB, `decompressobj().decompress()` sans `max_length`), et les encodages chaînés sont acceptés sans limite. Mesuré (`tracemalloc`, chunks 64 KiB) : `gzip` 100 MiB → 142 MiB alloués ; `gzip,gzip` (335 B sur le fil) → 210 MiB ; **`gzip,gzip,gzip` 512 MiB (245 B sur le fil) → 1,07 GiB alloués, RSS 2,1 GiB** avant le refus. Préexistant, identique avant/après `4d85fcd`. Atteignable depuis un Forgejo compromis ou un MITM si `verify_tls=false`. `br`/`zstd` : décodeurs absents du venv → identité → fail-closed ; s'aggraverait si `httpx[brotli]` était installé. Correctif : `Accept-Encoding: identity` + refus de tout `Content-Encoding`, ou `aiter_raw()` borné sur le fil + décodage manuel avec `max_length`/`unconsumed_tail`, et refus des `Content-Encoding` multi-valués. |
2. 🟡 BASSE (préexistant) — **une requête acceptée pendant une transaction de révocation ouverte** : le bearer a fini ses contrôles puis bloque sur `UPDATE mcp_tokens SET last_used_at` (verrou de ligne tenu par la révocation) ; au commit de celle-ci, la requête déjà validée est **acceptée** (re-auth → refusée). Fenêtre = durée de la transaction de révocation, non bornée (aucun `lock_timeout`/`statement_timeout`). Correctif : `UPDATE … WHERE enabled AND revoked_at IS NULL` + `rowcount != 1` ⇒ refus.
3. 🟡 BASSE — `revoke_oauth_family` sur famille absente retourne `()` **sans rien révoquer** tandis que `revoke_token` journalise `oauth.token_family_revoked` (audit trompeur). Inatteignable après migration (NOT NULL + FK) ; à durcir en échec explicite.
4. 🟡 BASSE — `grace=0` strict : garde codée (`grace_seconds > 0 and …`), **aucun test dédié** dans la suite, ni avant ni après (la preuve des tours 3 et 4 est un témoin de l'auditeur).

### État après quatrième contre-audit

| | |
|---|---|
| CRITIQUE | 0 |
| HAUTE | 0 dans l'arbre local — **1 sur la PR publique** (`cf40e9b`, régression rotation/révocation reconnue par le mainteneur, correctif non poussé) |
| MOYENNE | 2 : bombe de décompression (préexistante, réfute le 1ᵉʳ audit) ; migration `0011` ignorant les révocations dashboard antérieures |
| BASSE | ~6 : redaction (scp-like, `1234:5678@`, faux positif), requête acceptée pendant révocation ouverte, no-op silencieux, `grace=0` sans test, paire servie à utilisateur désactivé, co-livraison disposition/correctif |

**Actions prioritaires** : (1) **pousser** `4d85fcd`+`6dd04a5` ou retirer la PR de la revue tant que la HAUTE y figure ; (2) borner la décompression sur le fil ; (3) compléter le backfill de `0011` avec `mcp_tokens.revoked_at` ; (4) scinder en 3 PR comme demandé par le mainteneur. Le socle OAuth est maintenant réellement conforme RFC 9700 dans la grâce, et le bearer reste fail-closed sur tous les chemins testés — mais deux clôtures « Corrigé » de plus se sont révélées partielles au rejeu des témoins d'origine, et une revendication du premier audit externe (le mien) est tombée : un « plafonné avant bufferisation » se mesure avec un corps compressé, pas seulement avec un corps clair.

---

## 🔁🔁🔁🔁🔁 Cinquième contre-audit — plage `b40124c..e0f8852` (2026-09-08, soir)

> Note Claude — contre-vérification adverse des 4 commits `081e254` (borne de décompression), `26fc722` (migration `0012`, révocations dashboard héritées), `44137c0` (redaction), `e0f8852` (docs `adverse-audit-followup-2026-09-08.md`). Témoins rejoués sur le **vrai chemin streaming** (flux `aiter_raw` ET vrai serveur HTTP local via httpcore — le mainteneur signale à juste titre que les transports préchargés sont hors frontière), PostgreSQL 16 jetable pour la migration avec 13 familles semées à `0010`, 26+ témoins de redaction. Intégrité : `/usr/bin/git`, `gh pr view` authentifié. Aucun fichier du code modifié.

### 🛑 Publication — inchangé, aggravé

`ls-remote` et `gh pr view 3` concordent : **PR #3 toujours à `cf40e9b`**, désormais **7 commits non poussés** (lot scripté en 2 s). **La HAUTE reconnue par le mainteneur reste sur la PR publique.** Le document de suivi élude ce point (« must be verified separately ») au lieu de le nommer. Poussée telle quelle, la PR unique porterait maintenant deux migrations (`0011`, `0012`) que le mainteneur avait demandé d'isoler.

### Intégrité : ✅ confirmée

Périmètre conforme aux messages, rien hors sujet, aucune dépendance/CI/Docker touchée, aucun code suspect, **zéro assertion ou test supprimé**, aucun secret (instrument validé 4/4), docs en ajout pur, **co-livraison disposition/correctif enfin séparée** (commit docs distinct). Ré-exécuté : **151 unit passed**, 162 collectés, ruff/mypy verts, `alembic heads` = `0012` unique. Non vérifiable ici : « 161 passed » avec PostgreSQL.

### Verdict par constat du 4ᵉ contre-audit

| Constat | Verdict adverse |
|---|---|
| A — MOY. bombe de décompression | ✅ **CORRIGÉ.** Le client lit `aiter_raw` et décode lui-même avec `max_length` ; encodages chaînés refusés **avant tout décodage** : `gzip,gzip,gzip` 512 MiB (243 B sur le fil) → pic **0,01 MiB** flux / 0,28 MiB vrai serveur (contre 1,07 GiB au 4ᵉ tour) ; gzip 100 MiB → 20,2 MiB (≈ 2 × plafond + chunk, le ×2 = tampon de sortie zlib), identique sur vrai serveur ; `br`/`zstd`/`x-gzip` → refus ; en-tête menteur → refus ; `Content-Length` menteur → refus. Témoins positifs : 9,9 MiB depuis 10 KiB gzip → ACCEPT **identique octet à octet** ; exactement 10 MiB → ACCEPT ; 10 MiB + 1 → REJECT ; pas de troncature silencieuse (`unconsumed_tail` jamais non vide avant `MAX+1`). Unique point de sortie HTTP vérifié (`client.stream` → `_bounded_response`). Transport préchargé : 209 MiB déjà alloués dans `Response.__init__` avant le refus de taille finale — hors frontière, documenté, sans effet en prod (transport httpx streame). **Prix en disponibilité (fail-closed)** : deflate brut sans en-tête zlib désormais refusé ; gzip multi-membres (`cat a.gz b.gz`) refusé (httpx ne décodait de toute façon que le premier membre — l'ancien comportement était lui-même faux) ; **corps vide + `Content-Encoding: gzip` → « Truncated »** alors que 5 endpoints attendent un 204 — un reverse proxy qui pose l'en-tête sur un 204 vide les casse. Le test du mainteneur (1 MiB / 16 MiB, `peak < 5×`) est un vrai témoin borné mais mono-couche ; la bombe chaînée n'est couverte que par `not is_stream_consumed` (assertion plus forte, mais variante). |
| B — MOY. migration `0011` ignorant les révocations dashboard antérieures | ✅ **CORRIGÉ, aucune sur-révocation.** 13 familles semées à `0010`, montée `0011` (les `F_dash_legacy*` restent `None`, comme au 4ᵉ tour) puis `0012`, puis **service réel** (bearer + refresh) : F_dash_legacy (avec ou sans audit), F_dash_legacy_rotated (audit présent, R1/M1 vivants → famille entière coupée), F_partial → **REVOKED, bearer et refresh refusés** ; F_alive (rotation saine) → intacte, refresh OK ; F_static → non touché ; faux positif recherché et non trouvé (l'action `mcp_token.revoked` n'est écrite que par le dashboard, jamais par la rotation). Idempotent ×2 (md5 des 4 tables identiques), downgrade no-op documenté, tête unique. **Sous-révocation résiduelle documentée** : F_dash_legacy_rotated_**noaudit** (révocation dashboard suivie d'une rotation, audit absent) est indiscernable d'une rotation saine → reste vivante ; aucun code de purge d'audit dans `src/`, donc atteignable seulement par suppression manuelle en base. Réserve : le test du mainteneur est une **variante** (tables ad hoc réduites, sans schéma Alembic réel ni service, sauté sans PostgreSQL) — la preuve ci-dessus est celle de l'auditeur. |
| C — BASSE redaction | ⚠️ **PARTIEL — fuites d'origine closes, deux régressions.** Clos : `git clone bot:ghp_secret@example.test:o/r.git`, `git:ghp_x@github.com:o/r.git`, `1234:5678@host/r`, `0000:1234@10.0.0.1/x`, `bot:pa/ss@host/r`, parenthèses/guillemets/point final, `24:00@`/`12:60@` (12 fuites). Intacts : `12:30@office`, `meeting 12:30@office/room`, `user@example.com`, `git@github.com:o/r.git`, `time 09:45@site/log`. **Régression fuite** : `bot:ghp(leak)@host/r` était redigé, **fuit** maintenant (parenthèses retirées du jeu de caractères de l'autorité). **Régression faux positif** : `ratio 1:2@scale` était intact, redigé maintenant (exemption `isdecimal` remplacée par HH:MM strict). Non corrigé et reconnu : `release:v2@stable/notes`. Terminateurs toujours ouverts (préexistant) : `, ; [ ] < > ? #`. Couche audit persistée uniquement ; sévérité BASSE inchangée. |

### Sort des 7 résidus du 4ᵉ tour

| Résidu | Disposition réelle |
|---|---|
| (a) requête bearer acceptée pendant une révocation ouverte | **Déclaré ouvert** par le mainteneur, non traité |
| (b) `revoke_oauth_family` no-op silencieux + audit trompeur | **Passé sous silence** |
| (c) `grace=0` sans test dédié | **Passé sous silence** (aucun test ajouté) |
| (d) paire servie à utilisateur désactivé (cache chaud) | **Déclaré ouvert**, non traité |
| (e) commits non poussés / HAUTE sur la PR | **Éludé** (ni chiffré ni nommé) — 7 non poussés |
| (f) scission en 3 PR | **Déclaré ouvert**, non fait |
| (g) co-livraison disposition/correctif | ✅ **Traité** (commit docs séparé) |

### État après cinquième contre-audit

| | |
|---|---|
| CRITIQUE | 0 |
| HAUTE | 0 dans l'arbre local — **1 sur la PR publique** (inchangé depuis le 4ᵉ tour) |
| MOYENNE | **0** applicative résiduelle (les deux du 4ᵉ tour sont réellement corrigées, prouvé sur chemin réel et PostgreSQL réel) |
| BASSE | ~8 : redaction (2 régressions + 1 faux positif reconnu + terminateurs), (a) (b) (c) (d), 204 vide + en-tête gzip cassant 5 endpoints, sous-révocation sans audit |

**Actions prioritaires** : (1) **pousser** — ou retirer la PR de revue : c'est le seul point HAUTE et il ne dépend d'aucun code ; (2) traiter les résidus (a) et (b) (quelques lignes chacun : `UPDATE … WHERE revoked_at IS NULL` + rowcount ; échec explicite sur famille absente) ; (3) tolérer le corps vide avec `Content-Encoding` sur les 204 ; (4) ajouter le test `grace=0` ; (5) scinder en 3 PR. Le code local est maintenant au niveau que le premier audit croyait déjà atteint — mais il n'est pas là où les relecteurs le regardent.

---

## 🎯 Verdict initial de l'audit, conservé à titre historique

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
