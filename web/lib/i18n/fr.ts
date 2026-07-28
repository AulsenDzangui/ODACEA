// Catalogue de chaînes UI — français.
// Source de vérité de la *forme* du catalogue : toute autre locale (ex. `en`)
// doit satisfaire le type `Messages` dérivé de cet objet. Les PROMPTS restent
// en français côté backend (hors périmètre i18n).
//
// Convention : regrouper par surface (breadcrumb, status, upload…). Les valeurs
// dynamiques passent par des fonctions (`(n) => ...`) plutôt que par
// concaténation côté composant, pour rester traduisibles.

export const fr = {
  breadcrumb: {
    aria: "Étapes du wizard",
    upload: "Étape 1 - Import CSV",
    audit: "Étape 2 - Audit",
    classement: "Étape 3 - Classement",
  },
  status: {
    healthy: "Serveur de traitement connecté",
    down: "Serveur de traitement injoignable",
    unknown: "Vérification du serveur de traitement…",
    providerCloud: "Cloud",
    providerLocal: "Local",
    providerDemo: "Démonstration",
    backendDownTitle: "Serveur de traitement injoignable",
    backendDownBody:
      "Le backend n'est pas accessible. Vérifiez votre connexion ou redémarrez le serveur.",
  },
  onboarding: {
    noFileYet: "Pas encore de fichier ?",
    loadDemo: "Charger un jeu de démonstration",
    loading: "Chargement…",
    openGuide: "Consulter le guide",
  },
  enrich: {
    title: "Enrichissement local (étape 0, facultatif)",
    intro:
      "Extraire des informations sur chaque fichier pour compléter « Content.Description ». Sans appel LLM, l'enrichissement est utile quand les noms de fichiers ne suffisent pas à décrire le contenu.",
    accessWarningTitle: "Cette étape lit le contenu des fichiers",
    accessWarningBody:
      "Contrairement au reste du traitement (métadonnées seules), l'enrichissement ouvre les fichiers pour en extraire du texte. Tout reste local ; rien n'est envoyé à un service distant. Si le contenu est sensible, utilisez un modèle local pour l'audit et le classement : « Content.Description » sera transmis au modèle.",
    sourceRootLabel: "Racine locale du vrac",
    sourceRootPlaceholder: "ex. D:\\archives\\service_scolarite",
    sourceRootHelp:
      "Le dossier réellement analysé par Archifiltre, accessible depuis la machine qui héberge le backend.",
    fingerprintLabel: "Détecter les doublons stricts (empreinte SHA-256)",
    overwriteLabel: "Réécrire les descriptions déjà renseignées",
    run: "Enrichir le vrac",
    running: "Enrichissement en cours…",
    successTitle: "Vrac enrichi",
    download: "Télécharger le CSV enrichi",
    descriptionSummary: (enriched: number, total: number) =>
      `${enriched} description(s) ajoutée(s) sur ${total} fichier(s).`,
    descriptionDetail: (
      alreadyFilled: number,
      noText: number,
      unsupported: number,
      missing: number,
    ) =>
      `Déjà renseignées : ${alreadyFilled} · Sans texte exploitable : ${noText} · Format non pris en charge : ${unsupported} · Introuvables : ${missing}.`,
    fingerprintSummary: (hashed: number, total: number) =>
      `${hashed} empreinte(s) calculée(s) sur ${total} fichier(s).`,
    duplicatesSummary: (groups: number, redundant: number) =>
      groups > 0
        ? `${groups} groupe(s) de doublons stricts — ${redundant} fichier(s) redondant(s).`
        : "Aucun doublon strict détecté.",
    descriptionUsedNotice:
      "L'option « Inclure la description » a été activée : l'audit et le classement transmettront « Content.Description » au modèle.",
    errorTitle: "Enrichissement impossible",
  },
  noteTemplates: {
    refonteLibreLabel: "Refonte libre",
    refonteLibreTitle:
      "Le prompt conserve par défaut l'ordre existant du fonds ; insère dans la note une consigne levant cette conservation pour concevoir le plan librement (texte modifiable)",
  },
  agent: {
    title: "Agent",
    nav: "Agent",
    subtitle:
      "Mode conversationnel : explorez et recherchez dans le vrac (volumes, types, périodes, doublons…). Agent lecture seule — aucune capacité de classement ni de renommage.",
    backToApp: "Retour à l'application",
    close: "Fermer",
    // Création de session — l'agent est lié au projet courant : la session
    // démarre automatiquement depuis le CSV chargé, sans étape d'import.
    startTitle: "Démarrer une session",
    noProjectCsv:
      "Aucun CSV n'est chargé dans le projet. Importez un vrac dans l'application pour démarrer l'agent.",
    retry: "Réessayer",
    creating: "Création de la session…",
    sessionInfo: (rows: number, ttlMin: number) =>
      `Session créée avec ${rows.toLocaleString("fr-FR")} ligne(s). Expire après ${ttlMin} min d'inactivité.`,
    sessionExpiredRecreating: "Session serveur expirée — recréation depuis le projet…",
    // Rapport d'audit en contexte (0.6.0)
    useAuditReport: "Donner le rapport d'audit à l'agent",
    auditReportActive: "L'agent a lu le rapport d'audit du projet",
    useAuditReportHint:
      "Injecte le rapport d'audit du projet dans le contexte de l'agent (constats + plan proposé). Le basculer recrée la session : la conversation en cours repart.",
    // Chat
    inputPlaceholder:
      "ex. « Quelles sont les principales thématiques du fonds ? »…",
    send: "Envoyer",
    stop: "Arrêter",
    copyConversation: "Copier la conversation",
    conversationCopied: "Conversation copiée",
    resetConversation: "Réinitialiser la conversation (l'agent repart sans mémoire)",
    you: "Vous",
    assistant: "Agent",
    thinking: "L'agent travaille…",
    toolCall: (name: string) => `Outil ${name}`,
    toolArguments: "Arguments",
    toolResult: "Résultat",
    emptyChat: "Envoyez un message pour démarrer la conversation.",
    usageSession: (tokens: string) => `Tokens cumulés sur la session : ${tokens}`,
    costSession: (cost: string) =>
      `Coût indicatif cumulé : ${cost} (grille locale, hors remises de cache)`,
    steps: (n: number) => `${n} étape(s) d'outils`,
    // Erreurs
    errorTitle: "Erreur",
    demoDisabled:
      "L'agent n'est pas disponible en mode démonstration (il introduit un état de session côté serveur).",
  },
  dashboard: {
    title: "Statistiques de projets",
    nav: "Statistiques",
    subtitle:
      "Synthèse locale des projets traités sur cet appareil : volumes, conformité au plan et durées.",
    empty:
      "Aucun projet enregistré pour l'instant. Les projets que vous traitez et sauvegardez apparaîtront ici.",
    backToApp: "Retour à l'application",
    cardProjects: "Projets",
    cardProjectsHint: (completed: number) => `dont ${completed} menés à terme`,
    cardVolume: "Fichiers audités",
    cardVolumeHint: (classified: number) => `${classified} classés`,
    cardConformity: "Conformité au plan",
    cardConformityHint: (measured: number) =>
      measured > 0
        ? `mesurée sur ${measured} projet${measured > 1 ? "s" : ""}`
        : "aucune mesure disponible",
    cardDuration: "Durée cumulée",
    cardTokens: "Tokens cumulés",
    cardAnomalies: "Écarts au plan",
    cardAnomaliesHint: (malformed: number) =>
      `${malformed} cible(s) malformée(s)`,
    tableCaption: "Détail par projet",
    colProject: "Projet",
    colDate: "Enregistré",
    colStatus: "Étape",
    colVolume: "Fichiers",
    colClassified: "Classés",
    colConformity: "Conformité",
    colDuration: "Durée",
    statusUpload: "Import",
    statusAudit: "Audit",
    statusClassement: "Classement",
    conformityMatch: "Conforme",
    conformityOffPlan: (off: number) => `${off} hors plan`,
    conformityUnmeasured: "Non mesurée",
    notApplicable: "—",
  },
} as const;
