"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { useWizard } from "@/lib/store";
import {
  DEFAULT_CLOUD_MODELS,
  DEFAULT_LOCAL_ENDPOINTS,
} from "@/lib/llm/config";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  CheckCircle2,
  XCircle,
  Loader2,
  Eye,
  EyeOff,
  Plug,
  Settings,
  Server,
  Cloud,
  Sliders,
  Pencil,
  Layers,
  Sun,
  Moon,
  Monitor,
  Palette,
  FileDown,
  ListTree,
  Info,
  type LucideIcon,
} from "lucide-react";
import { useThemeStore, type Theme } from "@/lib/theme-store";

const CUSTOM_MODEL_OPTION = "__custom__";

type SettingsSection = "model" | "tokens" | "batch" | "export" | "display";

const SECTIONS: {
  id: SettingsSection;
  label: string;
  icon: LucideIcon;
}[] = [
  { id: "model", label: "Modèle & connexion", icon: Plug },
  { id: "tokens", label: "Optimisation", icon: Sliders },
  { id: "batch", label: "Traitement par lots", icon: Layers },
  { id: "export", label: "Export", icon: FileDown },
  { id: "display", label: "Affichage", icon: Palette },
];

const THEME_OPTIONS: { id: Theme; label: string; icon: LucideIcon }[] = [
  { id: "light", label: "Clair", icon: Sun },
  { id: "dark", label: "Sombre", icon: Moon },
  { id: "system", label: "Système", icon: Monitor },
];

export function SettingsModal() {
  const {
    modelId,
    apiKey,
    baseUrl,
    providerMode,
    cloudModel,
    localEndpoint,
    localModel,
    tokenOptions,
    exportOptions,
    classementBatchSize,
    setProviderMode,
    setCloudModel,
    setLocalEndpoint,
    setLocalModel,
    setApiKey,
    setTokenOptions,
    setExportOptions,
    setClassementBatchSize,
    settingsModalOpen,
    setSettingsModalOpen,
  } = useWizard();

  const { theme, setTheme } = useThemeStore();

  const [section, setSection] = useState<SettingsSection>("model");
  const [showKey, setShowKey] = useState(false);
  const [testStatus, setTestStatus] = useState<
    "idle" | "loading" | "ok" | "error"
  >("idle");
  const [testError, setTestError] = useState("");

  // Le toggle « Inclure la description » n'est affiché qu'à l'étape audit.
  // Quand « Filtrer les colonnes » y est désactivé, toutes les colonnes (dont
  // Content.Description) sont transmises de toute façon : le toggle n'a alors
  // plus d'effet et est verrouillé sur « inclus ».
  const descInclLocked = !tokenOptions.filterColumns;

  const handleTest = async () => {
    setTestStatus("loading");
    setTestError("");
    try {
      const res = await fetch("/api/py/validate-connection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: modelId, apiKey, baseUrl }),
      });
      const data = (await res.json()) as { ok: boolean; error?: string };
      if (data.ok) {
        setTestStatus("ok");
      } else {
        setTestStatus("error");
        setTestError(data.error ?? "Échec");
      }
    } catch (err) {
      setTestStatus("error");
      setTestError(err instanceof Error ? err.message : String(err));
    }
  };

  const renderApiKeyField = (id: string, label: string, helper: string) => (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <div className="relative">
        <Input
          id={id}
          type={showKey ? "text" : "password"}
          placeholder="sk-..."
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          className="pr-9"
        />
        <button
          type="button"
          onClick={() => setShowKey((v) => !v)}
          aria-label={showKey ? "Masquer la clé API" : "Afficher la clé API"}
          aria-pressed={showKey}
          className="absolute right-1 top-1/2 inline-flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded text-(--ink-400) hover:text-(--ink-600) focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          {showKey ? (
            <EyeOff className="h-4 w-4" />
          ) : (
            <Eye className="h-4 w-4" />
          )}
        </button>
      </div>
      {helper && <p className="text-xs text-(--ink-500)">{helper}</p>}
    </div>
  );

  const active = SECTIONS.find((s) => s.id === section) ?? SECTIONS[0];

  return (
    <Dialog open={settingsModalOpen} onOpenChange={setSettingsModalOpen}>
      <DialogContent className="gap-0 overflow-hidden p-0 sm:max-w-2xl">
        <div className="flex h-[min(34rem,80vh)]">
          {/* ── Navigation latérale ─────────────────────────────────────── */}
          <nav className="flex w-52 shrink-0 flex-col border-r bg-muted/30 p-3">
            <DialogHeader className="px-2 pt-1 pb-3">
              <DialogTitle className="flex items-center gap-1.5">
                <Settings className="h-4 w-4" />
                Paramètres
              </DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-0.5">
              {SECTIONS.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setSection(id)}
                  aria-current={section === id ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                    section === id
                      ? "bg-(--ink-100) font-medium text-(--ink-900)"
                      : "text-(--ink-600) hover:bg-(--ink-100)/60 hover:text-(--ink-900)",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  {label}
                </button>
              ))}
            </div>
          </nav>

          {/* ── Panneau de la section active ────────────────────────────── */}
          <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
            {/* Espaceur alignant le contenu sur le premier onglet : il réserve
                la hauteur exacte du bloc « Paramètres » de la nav
                (p-3 haut 12 + pt-1 4 + titre 16 + pb-3 12 = 44px), pour que
                « Paramètres » reste seul sur sa ligne. */}
            <div aria-hidden className="shrink-0 px-5 pt-3">
              <div className="px-2 pt-1 pb-3">
                <div className="h-4" />
              </div>
            </div>

            <div className="min-w-0 flex-1 overflow-y-auto px-5 pb-5">
            <DialogDescription className="sr-only">
              {active.label}
            </DialogDescription>

            {/* ── Modèle & connexion ────────────────────────────────────── */}
            {section === "model" && (
              <section className="space-y-4">
                <header className="space-y-1">
                  <h2 className="font-heading text-base font-medium text-(--ink-900)">
                    Modèle &amp; connexion
                  </h2>
                  <p className="text-sm text-(--ink-500)">
                    Fournisseur, modèle et clé d&apos;API utilisés pour
                    l&apos;audit et le classement.
                  </p>
                </header>

                <Tabs
                  value={providerMode}
                  onValueChange={(v) => setProviderMode(v as "cloud" | "local")}
                >
                  <TabsList className="w-full">
                    <TabsTrigger value="cloud">
                      <Cloud className="h-3.5 w-3.5" />
                      Cloud
                    </TabsTrigger>
                    <TabsTrigger value="local">
                      <Server className="h-3.5 w-3.5" />
                      Local
                    </TabsTrigger>
                  </TabsList>

                  {/* ── Onglet Cloud ──────────────────────────────────────────── */}
                  <TabsContent value="cloud" className="space-y-4 pt-1">
                    <div className="space-y-2">
                      <Label htmlFor="model">Modèle</Label>
                      <Select
                        value={
                          DEFAULT_CLOUD_MODELS.includes(cloudModel)
                            ? cloudModel
                            : CUSTOM_MODEL_OPTION
                        }
                        onValueChange={(v) => {
                          if (v === CUSTOM_MODEL_OPTION) {
                            if (DEFAULT_CLOUD_MODELS.includes(cloudModel))
                              setCloudModel("");
                          } else {
                            setCloudModel(v);
                          }
                        }}
                      >
                        <SelectTrigger id="model" className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {DEFAULT_CLOUD_MODELS.map((m) => (
                            <SelectItem key={m} value={m}>
                              {m}
                            </SelectItem>
                          ))}
                          <SelectItem value={CUSTOM_MODEL_OPTION}>
                            <Pencil className="mr-1 h-3.5 w-3.5" />
                            Saisie libre...
                          </SelectItem>
                        </SelectContent>
                      </Select>
                      {!DEFAULT_CLOUD_MODELS.includes(cloudModel) && (
                        <Input
                          placeholder="ex: claude-opus-4-8, gemini/gemini-2.5-pro"
                          value={cloudModel}
                          onChange={(e) => setCloudModel(e.target.value)}
                        />
                      )}
                    </div>

                    {renderApiKeyField("apikey-cloud", "Clé API", "")}
                  </TabsContent>

                  {/* ── Onglet Local ──────────────────────────────────────────── */}
                  <TabsContent value="local" className="space-y-4 pt-1">
                    <div className="space-y-2">
                      <Label htmlFor="endpoint">
                        Serveur (Ollama / LM Studio / JAN)
                      </Label>
                      <div className="flex gap-1">
                        {Object.entries(DEFAULT_LOCAL_ENDPOINTS).map(
                          ([name, url]) => (
                            <Button
                              key={name}
                              type="button"
                              variant={
                                localEndpoint === url ? "default" : "outline"
                              }
                              size="sm"
                              className="flex-1 text-xs"
                              onClick={() => setLocalEndpoint(url)}
                            >
                              {name}
                            </Button>
                          ),
                        )}
                      </div>
                      <Input
                        id="endpoint"
                        placeholder="http://localhost:1234/v1"
                        value={localEndpoint}
                        onChange={(e) => setLocalEndpoint(e.target.value)}
                      />
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="local-model">Modèle (optionnel)</Label>
                      <Input
                        id="local-model"
                        placeholder="nom du modèle"
                        value={localModel}
                        onChange={(e) => setLocalModel(e.target.value)}
                      />
                    </div>

                    {renderApiKeyField(
                      "apikey-local",
                      "Clé API (optionnel)",
                      "",
                    )}
                  </TabsContent>
                </Tabs>

                <Button
                  type="button"
                  variant="outline"
                  className="w-full"
                  onClick={handleTest}
                  disabled={testStatus === "loading"}
                >
                  {testStatus === "loading" && (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  )}
                  {testStatus === "ok" && (
                    <CheckCircle2 className="mr-2 h-4 w-4 text-(--success-500)" />
                  )}
                  {testStatus === "error" && (
                    <XCircle className="mr-2 h-4 w-4 text-(--danger-500)" />
                  )}
                  {testStatus === "idle" && <Plug className="mr-2 h-4 w-4" />}
                  Tester la connexion
                </Button>
                {testStatus === "error" && testError && (
                  <Alert variant="destructive">
                    <AlertDescription className="text-xs">
                      {testError}
                    </AlertDescription>
                  </Alert>
                )}
              </section>
            )}

            {/* ── Optimisation des tokens (étape audit) ─────────────────── */}
            {/* Préparation du CSV envoyé à AUD-001. Ces Paramètres prennent
                effet au (re)lancement de l'audit. */}
            {section === "tokens" && (
              <section className="space-y-3">
                <header className="space-y-1">
                  <h2 className="flex items-center gap-2 font-heading text-base font-medium text-(--ink-900)">
                    Optimisation des tokens
                    <span className="rounded bg-(--ink-100) px-1.5 py-0.5 text-xs font-normal text-(--ink-500)">
                      audit
                    </span>
                  </h2>
                  <p className="text-sm text-(--ink-500)">
                    Réduisent la taille du CSV envoyé à l&apos;audit (AUD-001).
                  </p>
                </header>

                <div className="flex items-center justify-between">
                  <Label htmlFor="filter" className="text-sm">
                    Filtrer les colonnes
                  </Label>
                  <Switch
                    id="filter"
                    checked={tokenOptions.filterColumns}
                    onCheckedChange={(v) =>
                      setTokenOptions({ filterColumns: v })
                    }
                  />
                </div>
                <div className="flex items-center justify-between">
                  <Label htmlFor="dates" className="text-sm">
                    Vider les dates des Items
                  </Label>
                  <Switch
                    id="dates"
                    checked={tokenOptions.cleanDates}
                    onCheckedChange={(v) => setTokenOptions({ cleanDates: v })}
                  />
                </div>
                <div className="flex items-center justify-between">
                  <Label htmlFor="sample" className="text-sm">
                    Échantillonner les fichiers
                  </Label>
                  <Switch
                    id="sample"
                    checked={tokenOptions.sampleItems}
                    onCheckedChange={(v) => setTokenOptions({ sampleItems: v })}
                  />
                </div>
                {/* Mesures automatiques — chiffres exacts (volumétrie, formats)
                    calculés par le moteur et fournis à l'IA comme référence, pour
                    fiabiliser ses comptes. L'analyse (doublons, nommage, bruit)
                    reste faite par l'IA. */}
                <div className="flex items-center justify-between">
                  <Label
                    htmlFor="autoMeasures"
                    className="flex items-center gap-1.5 text-sm"
                  >
                    Mesures automatiques
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          aria-label="À propos des mesures automatiques"
                          className="inline-flex text-(--ink-400) hover:text-(--ink-600) focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                        >
                          <Info className="h-3.5 w-3.5" />
                        </button>
                      </TooltipTrigger>
                      <TooltipContent>
                        Calcule automatiquement la volumétrie et les formats du
                        vrac et les fournit à l&apos;IA, pour fiabiliser ses
                        chiffres. L&apos;analyse (doublons, nommage…) reste faite
                        par l&apos;IA.
                      </TooltipContent>
                    </Tooltip>
                  </Label>
                  <Switch
                    id="autoMeasures"
                    checked={tokenOptions.autoMeasures}
                    onCheckedChange={(v) => setTokenOptions({ autoMeasures: v })}
                  />
                </div>
                {tokenOptions.sampleItems && (
                  <div className="space-y-1">
                    <Label htmlFor="sampleN" className="text-xs">
                      Max Items / dossier
                    </Label>
                    <Input
                      id="sampleN"
                      type="number"
                      min={1}
                      max={50}
                      value={tokenOptions.sampleItemsN}
                      onChange={(e) =>
                        setTokenOptions({
                          sampleItemsN: Math.max(
                            1,
                            parseInt(e.target.value, 10) || 1,
                          ),
                        })
                      }
                    />
                  </div>
                )}
                {/* Inclure la description — réglé ici (étape audit) mais appliqué
                aussi au classement via l'état persistant. Verrouillé sur
                « inclus » quand le filtrage des colonnes est désactivé (la
                colonne passe alors de toute façon). */}
                <div className="flex items-center justify-between">
                  <Label
                    htmlFor="includeDescription"
                    className={`text-sm ${descInclLocked ? "text-(--ink-400)" : ""}`}
                  >
                    Inclure la description
                  </Label>
                  <Switch
                    id="includeDescription"
                    checked={descInclLocked || tokenOptions.includeDescription}
                    disabled={descInclLocked}
                    onCheckedChange={(v) =>
                      setTokenOptions({ includeDescription: v })
                    }
                  />
                </div>
              </section>
            )}

            {/* ── Traitement par lots (étape classement) ────────────────── */}
            {/* Découpage en lots pour CLA-001. */}
            {section === "batch" && (
              <section className="space-y-3">
                <header className="space-y-1">
                  <h2 className="flex items-center gap-2 font-heading text-base font-medium text-(--ink-900)">
                    Traitement par lots
                    <span className="rounded bg-(--ink-100) px-1.5 py-0.5 text-xs font-normal text-(--ink-500)">
                      classement
                    </span>
                  </h2>
                  <p className="text-sm text-(--ink-500)">
                    Découpage des items envoyés au classement (CLA-001).
                  </p>
                </header>

                <div className="space-y-1">
                  <Label htmlFor="batchSize" className="text-xs">
                    Nombre d&apos;items par lot
                  </Label>
                  <Input
                    id="batchSize"
                    type="number"
                    min={50}
                    value={classementBatchSize}
                    onChange={(e) => {
                      const v = parseInt(e.target.value, 10);
                      setClassementBatchSize(isNaN(v) ? 50 : v);
                    }}
                    onBlur={() => {
                      if (classementBatchSize < 50)
                        setClassementBatchSize(50);
                    }}
                  />
                  {classementBatchSize < 50 && (
                    <p className="text-xs text-destructive">
                      La valeur minimale est 50.
                    </p>
                  )}
                </div>
              </section>
            )}

            {/* ── Export (étape classement) ─────────────────────────────── */}
            {/* Mise en forme du CSV téléchargé. Appliquée au moment du
                téléchargement uniquement ; n'altère pas le classement produit
                par l'IA. Préférences habituelles, persistées entre sessions. */}
            {section === "export" && (
              <section className="space-y-4">
                <header className="space-y-1">
                  <h2 className="flex items-center gap-2 font-heading text-base font-medium text-(--ink-900)">
                    Export du CSV
                    <span className="rounded bg-(--ink-100) px-1.5 py-0.5 text-xs font-normal text-(--ink-500)">
                      classement
                    </span>
                  </h2>
                  <p className="text-sm text-(--ink-500)">
                    Mise en forme des titres dans le CSV final. Ces réglages
                    s&apos;appliquent au téléchargement, sans relancer le
                    classement.
                  </p>
                </header>

                {/* Titre des dossiers = nom technique de l'arborescence */}
                <div className="flex items-center justify-between gap-2">
                  <Label
                    htmlFor="folder-title-from-file"
                    className="flex items-center gap-1.5 text-sm"
                  >
                    <ListTree className="h-3.5 w-3.5" />
                    Appliquer le titre technique des dossiers
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          aria-label="À propos du titre technique des dossiers"
                          className="inline-flex text-(--ink-400) hover:text-(--ink-600) focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                        >
                          <Info className="h-3.5 w-3.5" />
                        </button>
                      </TooltipTrigger>
                      <TooltipContent>
                        Par défaut, le Content.Title des dossiers reprend le
                        titre hiérarchique (ex. Inscriptions effectifs), adapté
                        à un SAE SEDA. Activez pour utiliser le nom technique du
                        champ File (ex. 1-1_Inscriptions_effectifs), plus
                        pratique pour un export sur disque.
                      </TooltipContent>
                    </Tooltip>
                  </Label>
                  <Switch
                    id="folder-title-from-file"
                    checked={exportOptions.folderTitleFromFile}
                    onCheckedChange={(v) =>
                      setExportOptions({ folderTitleFromFile: v })
                    }
                  />
                </div>

                {/* Titre des fichiers = titre d'origine (rejet du renommage IA) */}
                <div className="flex items-center justify-between gap-2">
                  <Label
                    htmlFor="keep-original-file-title"
                    className="flex items-center gap-1.5 text-sm"
                  >
                    <FileDown className="h-3.5 w-3.5" />
                    Conserver le titre d&apos;origine des fichiers
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          aria-label="À propos du titre d'origine des fichiers"
                          className="inline-flex text-(--ink-400) hover:text-(--ink-600) focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                        >
                          <Info className="h-3.5 w-3.5" />
                        </button>
                      </TooltipTrigger>
                      <TooltipContent>
                        Par défaut, le Content.Title des fichiers reprend le nom
                        proposé par l&apos;IA au classement. Activez pour
                        rétablir le titre d&apos;origine du CSV importé sans
                        impact sur les autres éléments (dossiers, dates).
                      </TooltipContent>
                    </Tooltip>
                  </Label>
                  <Switch
                    id="keep-original-file-title"
                    checked={exportOptions.keepOriginalFileTitle}
                    onCheckedChange={(v) =>
                      setExportOptions({ keepOriginalFileTitle: v })
                    }
                  />
                </div>
              </section>
            )}

            {/* ── Affichage ─────────────────────────────────────────────── */}
            {section === "display" && (
              <section className="space-y-4">
                <header className="space-y-1">
                  <h2 className="font-heading text-base font-medium text-(--ink-900)">
                    Affichage
                  </h2>
                  <p className="text-sm text-(--ink-500)">
                    Apparence de l&apos;interface.
                  </p>
                </header>

                <div className="space-y-2">
                  <Label className="text-sm">Thème</Label>
                  <div className="grid grid-cols-3 gap-2">
                    {THEME_OPTIONS.map(({ id, label, icon: Icon }) => (
                      <button
                        key={id}
                        type="button"
                        onClick={() => setTheme(id)}
                        className={cn(
                          "flex flex-col items-center gap-2 rounded-lg border px-3 py-4 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                          theme === id
                            ? "border-(--ink-700) bg-(--ink-100) font-medium text-(--ink-900)"
                            : "border-(--ink-200) text-(--ink-500) hover:border-(--ink-400) hover:text-(--ink-800)",
                        )}
                      >
                        <Icon className="h-5 w-5" />
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              </section>
            )}
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
