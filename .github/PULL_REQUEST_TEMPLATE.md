<!--
⚠️ ODACEA n'accepte pas de pull requests externes, elles ne seront pas fusionnées.
Voir CONTRIBUTING.md.

Pour signaler un bug ou proposer une amélioration, ouvrez plutôt une *issue*.

Ce gabarit ne concerne que les contributions internes du mainteneur.
-->

## Résumé

Décrivez le changement en une ou deux phrases.

## Type

- [ ] Correctif (bug)
- [ ] Fonctionnalité
- [ ] Refactorisation / documentation

## Vérifications

- [ ] `web/` : `npm run lint` et `npm run build` passent (si front modifié)
- [ ] `backend/` : la CLI et `uvicorn api.main:app` démarrent (si moteur/API modifié)
- [ ] Prompts modifiés : validés en les exécutant (approche cloud ou locale, au choix)
- [ ] Aucune donnée sensible ni secret (`.env`, clés API) introduit
