export const DEFAULT_MODEL = "gpt-5.1";

export const DEFAULT_CLOUD_MODELS = ["gpt-5.1", "gpt-5.4-mini-2026-03-17"];

export const DEFAULT_LOCAL_ENDPOINTS: Record<string, string> = {
  Ollama: "http://localhost:11434",
  "LM Studio": "http://localhost:1234/v1",
  JAN: "http://localhost:1337/v1",
};

// Préréglage proposé quand on bascule en mode Local sans endpoint défini.
export const DEFAULT_LOCAL_ENDPOINT = DEFAULT_LOCAL_ENDPOINTS["LM Studio"];

// Nom de modèle envoyé au serveur local quand l'utilisateur n'en saisit aucun
// (LM Studio / JAN ignorent ce nom et servent le modèle chargé).
export const LOCAL_MODEL_FALLBACK = "local-model";
