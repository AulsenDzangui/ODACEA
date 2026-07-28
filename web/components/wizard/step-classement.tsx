"use client";

import { useEffect, useRef, useState } from "react";
import { useWizard } from "@/lib/store";
import type {
  ClassementBatch,
  CorrectionExample,
  LlmClassementRow,
  SedaRow,
  ResipResult,
} from "@/lib/csv/types";
import { mergeCorrections } from "@/lib/csv/corrections";
import { anomaliesFromWarnings } from "@/lib/csv/anomalies";
import type { LlmUsage } from "@/lib/llm/client-stream";
import { stringifyCsv } from "@/lib/csv/parse";
import {
  parsePlanTree,
  parsePlanTitles,
  displayParts,
  sortKey,
} from "@/lib/csv/plan-tree";
import {
  addFolderToPlan,
  renameFolderInPlan,
  deleteFolderFromPlan,
  type FolderRename,
  type FolderDelete,
} from "@/lib/csv/plan-edit";
import { REQUIRED_COLUMNS } from "@/lib/csv/constants";
import {
  resolveConcurrency,
  resumableBatches,
  resumeStillValid,
  runBatchPool,
} from "@/lib/csv/batch-schedule";
import {
  streamSse,
  postJson,
  formatApiError,
  unmapUsage,
} from "@/lib/llm/client-stream";
import { TokenUsageBar, sumUsage } from "@/components/token-usage-bar";
import { formatDuration } from "@/lib/tokens/estimate";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { StreamingMarkdown } from "@/components/streaming-markdown";
import { ThinkingPanel } from "@/components/thinking-panel";
import { PlanTree } from "@/components/plan-tree";
import { CsvPreview } from "@/components/csv-preview";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { ArborescenceModal } from "@/components/arborescence-modal";
import { ReclassPanel } from "@/components/wizard/reclass-panel";
import { DirectivesPanel } from "@/components/wizard/directives-panel";
import { AnomaliesTable } from "@/components/wizard/anomalies-table";
import { ApplyPanel } from "@/components/wizard/apply-panel";
import { IconAction } from "@/components/wizard/icon-action";
import { DEMO_MODE } from "@/lib/llm/config";
import { StepActions } from "@/components/wizard/step-actions";
import {
  AlertCircle,
  Download,
  RotateCcw,
  Pencil,
  ListTree,
  StickyNote,
  BarChart3,
  Search,
  AlertTriangle,
  FileText,
  XCircle,
  Layers,
  Loader2,
  CircleStop,
  CheckCircle2,
  Circle,
  Printer,
  FolderTree,
  ChevronDown,
  MessageSquarePlus,
} from "lucide-react";

/** Suffixe d'accord pluriel français : "s" dès que n ≥ 2, "" sinon (0 et 1 =
 *  singulier). Renvoie un suffixe plutôt qu'un mot pour couvrir les accords
 *  multiples d'une même phrase : `item${plS(n)} envoyé${plS(n)}`. */
const plS = (n: number) => (n >= 2 ? "s" : "");

/** Horodatage epoch (ms) — isolé hors composant pour mesurer le temps mural du
 *  classement par lots sans déclencher la règle de pureté React sur `Date.now`
 *  (appelé dans des gestionnaires async, jamais au rendu). */
const nowMs = () => Date.now();

type BatchState = {
  itemCount: number;
  status: "pending" | "running" | "done" | "error";
  rows: LlmClassementRow[];
  rawText: string;
  thinking?: string;
  /** Estimation live des lignes produites (event `progress`), recalée sur
   *  `rows.length` une fois le lot terminé. */
  liveCount?: number;
  error?: string;
  /** Avis de classement du lot, quand il vient d'un run repris : la réponse
   *  brute n'est pas persistée (volume), seul cet extrait l'est. */
  preCsv?: string;
  usage?: LlmUsage | null;
  /** Durée de traitement du lot (ms) renvoyée par l'événement `done`. */
  durationMs?: number | null;
};

/** Avis de classement = prose que le modèle écrit *avant* le bloc CSV. On coupe à
 *  la première fence ```` ```csv ```` ; à défaut (modèles locaux qui omettent la
 *  fence) à la première ligne d'en-tête CLA (`Path;…`). Sans repère, on n'affiche
 *  rien plutôt que de prendre toute la réponse pour de l'avis. */
function extractAvis(raw: string): string {
  if (!raw) return "";
  const fenceIdx = raw.indexOf("```csv");
  const headerIdx = raw.search(/^\s*"?Path"?\s*[;,]/m);
  const cut = fenceIdx >= 0 ? fenceIdx : headerIdx;
  return cut >= 0 ? raw.slice(0, cut).trim() : "";
}

export function StepClassement() {
  const {
    csvOriginal,
    csvFilename,
    planValide,
    planValideOriginal,
    setPlanValide,
    planModifie,
    planOrigin,
    classementDirectives,
    setClassementDirectives,
    modelId,
    apiKey,
    baseUrl,
    tokenOptions,
    exportOptions,
    promptVersionAudit,
    promptVersionClassement,
    classementBatchSize,
    classementConcurrency,
    providerMode,
    classementRunning,
    setClassementRunning,
    setClassementResult,
    classementBatches,
    setClassementBatches,
    csvFinal,
    thinkingClassement,
    llmRawResponse,
    llmRawRows,
    lastError,
    setLastError,
    usageAudit,
    usageClassementTotal,
    setUsageClassementTotal,
    durationAudit,
    durationClassementTotal,
    setDurationClassementTotal,
    setPromptVersionClassement,
    modelAudit,
    modelClassement,
    setModelClassement,
  } = useWizard();

  const [streamText, setStreamText] = useState("");
  const [streamThinking, setStreamThinking] = useState("");
  const [confirmRelaunch, setConfirmRelaunch] = useState(false);
  const [arborescenceOpen, setArborescenceOpen] = useState(false);
  // Export du journal de traitement en cours — passe serveur sans LLM.
  const [journalBusy, setJournalBusy] = useState(false);
  // Export de l'arborescence modèle en cours — passe serveur sans LLM.
  const [manifestBusy, setManifestBusy] = useState(false);
  // Re-finalisation en cours (corrections) — passe Python pure, sans LLM.
  const [reclassBusy, setReclassBusy] = useState(false);
  // Apprentissage des corrections (opt-in) — corrections validées dans
  // cette session, à réinjecter comme exemples few-shot au prochain classement.
  // État de session volontairement non persisté : réactiver le few-shot (qui
  // *modifie le prompt*) reste une décision explicite à chaque session.
  const [corrections, setCorrections] = useState<CorrectionExample[]>([]);
  const [reinjectCorrections, setReinjectCorrections] = useState(false);
  // Volet de correction contrôlé : le triage des anomalies l'ouvre,
  // filtré sur l'item à corriger.
  const [reclassAccordion, setReclassAccordion] = useState("");
  const [reclassSearch, setReclassSearch] = useState("");

  const locateItem = (path: string) => {
    setReclassSearch(path);
    setReclassAccordion("reclass");
    requestAnimationFrame(() =>
      document
        .getElementById("reclass-panel")
        ?.scrollIntoView({ behavior: "smooth", block: "start" }),
    );
  };
  // Progression à l'unité en mode appel-unique (sous le seuil de lots).
  const [singleProgress, setSingleProgress] = useState<{
    done: number;
    total: number;
  } | null>(null);

  // ── État du mode batché ──────────────────────────────────────────────────
  // batchesRef = source de vérité (manipulée dans les boucles async) ;
  // batches = miroir pour le rendu.
  // Reprise d'un classement interrompu : les lots sont persistés au projet dès
  // qu'ils s'achèvent, donc un projet rouvert peut porter un classement à moitié
  // fait (onglet fermé, plantage, machine éteinte). On réarme alors l'état du
  // mode lot pour que la relance des lots restants — déjà offerte en session —
  // survive au rechargement, au lieu de repayer tous les lots réussis. Calculé
  // une seule fois, au montage (`useState` paresseux), avant tout ref.
  const [resumed] = useState<BatchState[] | null>(() => {
    if (csvFinal) return null; // classement abouti : rien à reprendre
    const resumable = resumableBatches(classementBatches, classementBatchSize);
    return (
      resumable?.map((b) => ({
        itemCount: b.itemCount,
        status: b.status === "done" ? ("done" as const) : ("error" as const),
        rows: b.rows,
        rawText: "",
        preCsv: b.preCsv,
        error: b.error,
      })) ?? null
    );
  });
  const batchesRef = useRef<BatchState[]>(resumed ?? []);
  const [batches, setBatchesState] = useState<BatchState[] | null>(
    resumed ? [...resumed] : null,
  );
  // Le corpus reste à vérifier avant la première relance par index (garde
  // `resumeStillValid`) : seuls les lots repris d'une session antérieure sont
  // concernés — ceux de la session courante ont été découpés à l'instant.
  const resumeUnverifiedRef = useRef(resumed !== null);
  const syncBatches = () => setBatchesState([...batchesRef.current]);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Réconciliation de l'option d'export « retirer les numéros de dossier »
  // (togglée depuis Paramètres → Export, un autre composant). Elle touche la
  // colonne File (structure) — appliquée côté moteur au finalize. Quand
  // l'archiviste la bascule alors qu'un classement est déjà finalisé, on
  // re-finalise (passe Python pure, sans LLM) pour que le CSV, le manifeste et la
  // copie physique héritent tous du même choix. `stripAppliedRef` retient le
  // dernier état appliqué : on ignore le montage / rechargement de projet (aucun
  // appel réseau surprise) et on ne réagit qu'à un vrai changement en session.
  const stripAppliedRef = useRef(exportOptions.stripFolderNumbers);
  useEffect(() => {
    const desired = exportOptions.stripFolderNumbers;
    if (desired === stripAppliedRef.current) return;
    stripAppliedRef.current = desired;
    if (!csvOriginal || !csvFinal || !llmRawRows || llmRawRows.length === 0) return;
    const rows = llmRawRows;
    const plan = planValide;
    // Re-finalisation autonome (passe RESIP Python pure, AUCUN appel LLM) : même
    // appel que `refinalize`, inliné ici pour ne dépendre que de valeurs déjà en
    // portée (le lint interdit de référencer `refinalize`, déclarée plus bas).
    // Déférée hors de l'effet pour éviter un setState synchrone (rendu en cascade).
    queueMicrotask(async () => {
      setReclassBusy(true);
      setLastError("");
      try {
        const fin = await postJson<{ resip: ResipResult; error?: string }>(
          "/classement/finalize",
          {
            csv: stringifyCsv(csvOriginal),
            planValide: plan,
            llmRows: rows,
            directives: classementDirectives,
            stripFolderNumbers: desired,
          },
        );
        if (fin.error) throw new Error(fin.error);
        setClassementResult(llmRawResponse, thinkingClassement, fin.resip, rows);
      } catch (err) {
        setLastError(formatApiError(err));
      } finally {
        setReclassBusy(false);
      }
    });
    // Seul le réglage déclenche la re-finalisation ; les autres valeurs sont lues
    // à l'exécution de l'effet (déclenché uniquement au changement du réglage).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exportOptions.stripFolderNumbers]);

  if (!csvOriginal || !planValide) {
    return (
      <Alert>
        <AlertCircle className="h-4 w-4" />
        <AlertTitle>Plan manquant</AlertTitle>
        <AlertDescription>
          Vous devez d&apos;abord lancer un audit.
        </AlertDescription>
      </Alert>
    );
  }

  const folderTree = parsePlanTree(planValide);
  const planTitles = parsePlanTitles(planValide);
  const folderTreeValid = Object.keys(folderTree).length > 0;

  // CSV brut + options de préparation envoyés au backend (qui prépare/classe/convertit).
  const csv = stringifyCsv(csvOriginal);
  const prep = {
    filterColumns: tokenOptions.filterColumns,
    cleanDates: tokenOptions.cleanDates,
    sampleItems: tokenOptions.sampleItems,
    sampleItemsN: tokenOptions.sampleItemsN,
    includeItems: !tokenOptions.foldersOnly,
    includeDescription: tokenOptions.includeDescription,
    classementAvis: tokenOptions.classementAvis,
    classementRef: tokenOptions.classementRef,
  };

  // Exemples few-shot envoyés au moteur uniquement si l'archiviste a activé
  // la réinjection ET qu'il existe des corrections. Sinon corps vide → prompt
  // CLA-001 inchangé (byte-identique à la 1.0.0 côté moteur). Transport pur : la
  // sélection/formulation du few-shot vit dans le moteur.
  const batchCorrections =
    reinjectCorrections && corrections.length > 0 ? corrections : [];

  // Consignes de classement de l'archiviste, persistées au projet et
  // **réutilisées à chaque relance** (contrairement au few-shot, opt-in par
  // session). Vide → prompt CLA-001 et conversion inchangés (byte-identique).
  // Transport pur : la sérialisation et la dérivation des dossiers à création
  // autorisée vivent dans le moteur (`core.cla_directives`).
  const batchDirectives = classementDirectives;
  // Sous-dossiers créés au dernier classement — rappel dans le panneau.
  const createdFolders = csvFinal?.stats?.foldersCreatedAuthorized ?? [];
  // Options de dossier du plan pour ancrer une consigne (libellés lisibles).
  const directiveFolderOptions = Object.keys(folderTree)
    .sort((a, b) => {
      const ka = sortKey(a);
      const kb = sortKey(b);
      for (let i = 0; i < Math.max(ka.length, kb.length); i++) {
        const d = (ka[i] ?? -1) - (kb[i] ?? -1);
        if (d !== 0) return d;
      }
      return a.localeCompare(b);
    })
    .map((tech) => {
      const title = planTitles[tech] ?? displayParts(tech).label;
      const { number } = displayParts(tech);
      return { tech, label: number ? `${number} ${title}` : title };
    });

  const runClassement = async () => {
    setStreamText("");
    setStreamThinking("");
    setLastError("");
    setSingleProgress(null);
    batchesRef.current = [];
    setBatchesState(null);
    setClassementBatches(null);
    // Découpage refait à l'instant : plus rien à vérifier avant une relance.
    resumeUnverifiedRef.current = false;

    abortControllerRef.current = new AbortController();

    // Le backend re-dérive les items ; on récupère juste le total pour décider du
    // découpage et afficher les compteurs.
    let total: number;
    try {
      const prepResp = await postJson<{ total: number; error?: string }>(
        "/classement/prepare",
        { csv, prep },
        abortControllerRef.current.signal,
      );
      if (prepResp.error) throw new Error(prepResp.error);
      total = prepResp.total;
    } catch (err) {
      setLastError(formatApiError(err));
      return;
    }

    // Sous le seuil : appel unique, streaming visible.
    if (total <= classementBatchSize) {
      setClassementRunning(true);
      setSingleProgress({ done: 0, total });
      let rawText = "";
      let rawReasoning = "";
      try {
        const result = await streamSse(
          "/classement/batch",
          { csv, planValide, model: modelId, apiKey, baseUrl, prep, batchIndex: 0, batchSize: 0, corrections: batchCorrections, directives: batchDirectives },
          {
            onText: (delta) => setStreamText((prev) => prev + delta),
            onReasoning: (delta) => setStreamThinking((prev) => prev + delta),
            onProgress: (p) => setSingleProgress({ done: p.itemsDone, total }),
            // Retry LLM en cours : visible dans le panneau de démarche.
            onNotice: (msg) =>
              setStreamThinking((prev) => `${prev}

> ⟳ ${msg}

`),
          },
          abortControllerRef.current.signal,
        );
        rawText = result.text;
        rawReasoning = result.reasoning;

        // Interruption par l'utilisateur. Un seul message ; on conserve tout de
        // même la réponse partielle du modèle plutôt que de la perdre.
        if (result.aborted) {
          setLastError("Classement arrêté par l'utilisateur");
          setClassementResult(rawText, rawReasoning, null);
          return;
        }

        const llmRows = (result.done?.llmRows as LlmClassementRow[]) ?? [];
        if (llmRows.length === 0) {
          throw new Error(
            "Aucune ligne CSV n'a pu être extraite de la réponse LLM. Vérifiez le format de sortie.",
          );
        }
        const fin = await postJson<{ resip: ResipResult; error?: string }>(
          "/classement/finalize",
          {
            csv,
            planValide,
            llmRows,
            directives: batchDirectives,
            stripFolderNumbers: exportOptions.stripFolderNumbers,
          },
        );
        if (fin.error) throw new Error(fin.error);
        setClassementResult(result.text, result.reasoning, fin.resip, llmRows);
        setUsageClassementTotal(result.usage);
        setDurationClassementTotal(
          typeof result.done?.durationMs === "number" ? result.done.durationMs : null,
        );
        // Version du prompt CLA-001 — consignée dans le projet.
        setPromptVersionClassement(
          typeof result.done?.promptVersion === "string"
            ? result.done.promptVersion
            : null,
        );
        // Modèle ayant exécuté le classement — figé pour la traçabilité.
        setModelClassement(
          typeof result.done?.model === "string" ? result.done.model : modelId,
        );
      } catch (err) {
        setLastError(formatApiError(err));
        // Conserve la réponse brute accumulée avant l'erreur (exploitable en
        // diagnostic), même si la conversion RESIP a échoué.
        setClassementResult(rawText, rawReasoning, null);
      } finally {
        setClassementRunning(false);
      }
      return;
    }

    // Au-dessus du seuil : lots découpés. Traités par un pool borné —
    // séquentiel par défaut, jusqu'à K en parallèle sur un fournisseur cloud,
    // forcé séquentiel en local. Le backend étant sans état, chaque lot est un
    // appel indépendant ; la finalisation réassemble par index, insensible à
    // l'ordre d'achèvement.
    const nBatches = Math.ceil(total / classementBatchSize);
    batchesRef.current = Array.from({ length: nBatches }, (_, i) => ({
      itemCount: Math.min(classementBatchSize, total - i * classementBatchSize),
      status: "pending" as const,
      rows: [],
      rawText: "",
    }));
    syncBatches();

    const k = resolveConcurrency(
      classementConcurrency,
      providerMode === "local",
      nBatches,
    );
    setClassementRunning(true);
    const t0 = nowMs();
    await runBatchPool(
      nBatches,
      k,
      runSingleBatch,
      () => abortControllerRef.current?.signal.aborted ?? false,
    );
    setClassementRunning(false);
    // En parallèle, la somme des durées de lot surestime : on rapporte le temps
    // mural de la phase (comme le CLI). En séquentiel, la somme fait foi.
    if (batchesRef.current.every((b) => b.status === "done"))
      await finalize(k > 1 ? nowMs() - t0 : undefined);
  };

  // Résumé léger des lots persisté avec le projet (sans les textes bruts, trop
  // volumineux pour localStorage — seul l'avis en est extrait). Écrit **après
  // chaque lot** et non plus seulement à la finalisation : une interruption en
  // cours de route ne doit pas faire perdre les lots déjà payés au LLM.
  const batchSummary = (): ClassementBatch[] =>
    batchesRef.current.map((b) => ({
      itemCount: b.itemCount,
      rows: b.rows,
      // Lot repris d'une session antérieure : pas de réponse brute en mémoire,
      // on reconduit l'avis déjà persisté plutôt que de l'effacer.
      preCsv: b.rawText ? extractAvis(b.rawText) : b.preCsv,
      status: b.status === "done" ? "done" : "error",
      error: b.status === "done" ? undefined : b.error,
    }));

  const runSingleBatch = async (i: number) => {
    const b = batchesRef.current[i];
    b.status = "running";
    b.error = undefined;
    b.rawText = "";
    b.thinking = "";
    b.liveCount = 0;
    syncBatches();
    try {
      const result = await streamSse(
        "/classement/batch",
        {
          csv,
          planValide,
          model: modelId,
          apiKey,
          baseUrl,
          prep,
          batchIndex: i,
          batchSize: classementBatchSize,
          corrections: batchCorrections,
          directives: batchDirectives,
        },
        {
          onText: (delta) => {
            b.rawText += delta;
            syncBatches();
          },
          onReasoning: (delta) => {
            b.thinking = (b.thinking ?? "") + delta;
            syncBatches();
          },
          onProgress: (p) => {
            b.liveCount = p.itemsDone;
            syncBatches();
          },
          onNotice: (msg) => {
            b.thinking = `${b.thinking ?? ""}

> ⟳ ${msg}

`;
            syncBatches();
          },
        },
        abortControllerRef.current?.signal,
      );

      // Interruption par l'utilisateur : on marque le lot en erreur mais on
      // conserve le texte brut déjà streamé (visible dans le volet du lot).
      if (result.aborted) {
        b.rawText = result.text || b.rawText;
        b.status = "error";
        b.error = "Lot arrêté par l'utilisateur";
        syncBatches();
        return;
      }

      const rows = (result.done?.llmRows as LlmClassementRow[]) ?? [];
      if (rows.length === 0) {
        throw new Error(
          "Aucune ligne CSV n'a pu être extraite de la réponse pour ce lot.",
        );
      }
      b.rows = rows;
      b.rawText = result.text;
      b.usage = result.usage;
      b.durationMs =
        typeof result.done?.durationMs === "number" ? result.done.durationMs : null;
      b.status = "done";
      // Version du prompt CLA-001 — identique pour tous les lots d'un run.
      setPromptVersionClassement(
        typeof result.done?.promptVersion === "string"
          ? result.done.promptVersion
          : null,
      );
      // Modèle ayant exécuté le classement — identique pour tous les lots.
      setModelClassement(
        typeof result.done?.model === "string" ? result.done.model : modelId,
      );
    } catch (err) {
      b.status = "error";
      b.error = formatApiError(err);
    }
    syncBatches();
    // Point de sauvegarde : l'auto-save du projet suit ce changement de store
    // (débouncé). Le lot qui vient de finir est acquis, même si la suite échoue.
    setClassementBatches(batchSummary());
  };

  const finalize = async (wallMs?: number) => {
    const all = batchesRef.current.flatMap((b) => b.rows);
    const joinedRaw = batchesRef.current.map((b) => b.rawText).join("\n\n");
    setClassementBatches(batchSummary());
    setUsageClassementTotal(sumUsage(batchesRef.current.map((b) => b.usage)));
    // Durée du classement : en parallèle, le temps mural de la phase fourni
    // par l'appelant (les lots se recouvrent) ; sinon la somme des durées de lot
    // (traitement séquentiel). null si rien de mesurable.
    const summedDuration = batchesRef.current.reduce(
      (acc, b) => acc + (b.durationMs ?? 0),
      0,
    );
    const totalDuration = wallMs ?? summedDuration;
    setDurationClassementTotal(totalDuration > 0 ? totalDuration : null);
    // Conversion RESIP en une seule passe sur l'ensemble des lots (backend).
    try {
      const fin = await postJson<{ resip: ResipResult; error?: string }>(
        "/classement/finalize",
        {
          csv,
          planValide,
          llmRows: all,
          directives: batchDirectives,
          stripFolderNumbers: exportOptions.stripFolderNumbers,
        },
      );
      if (fin.error) throw new Error(fin.error);
      setClassementResult(joinedRaw, "", fin.resip, all);
    } catch (err) {
      setLastError(formatApiError(err));
      setClassementResult(joinedRaw, "", null, all);
    }
  };

  // Re-finalise (passe RESIP Python pure, AUCUN appel LLM) avec `rows`/`plan`
  // donnés explicitement — `setPlanValide` étant asynchrone, on ne dépend jamais
  // de la valeur du store pour la passe en cours. Met à jour `csvFinal` (et donc
  // tout le rapport de couverture) ainsi que `llmRawRows` (devient la nouvelle
  // base classée). Rejette en cas d'erreur backend (affichée par l'appelant).
  const refinalize = async (
    rows: LlmClassementRow[],
    plan: string,
    // Option d'export « retirer les numéros » : passée explicitement lors d'une
    // bascule (setExportOptions étant asynchrone, on ne dépend pas de la valeur
    // du store dans la même passe) ; sinon la valeur courante du store.
    strip: boolean = exportOptions.stripFolderNumbers,
  ) => {
    setReclassBusy(true);
    setLastError("");
    try {
      const fin = await postJson<{ resip: ResipResult; error?: string }>(
        "/classement/finalize",
        {
          csv,
          planValide: plan,
          llmRows: rows,
          directives: batchDirectives,
          stripFolderNumbers: strip,
        },
      );
      if (fin.error) throw new Error(fin.error);
      setClassementResult(llmRawResponse, thinkingClassement, fin.resip, rows);
    } catch (err) {
      setLastError(formatApiError(err));
      throw err;
    } finally {
      setReclassBusy(false);
    }
  };

  // Réaligne les cibles des lignes déjà classées après un décalage de préfixe
  // (renommage/suppression d'un dossier) — sinon ces lignes viseraient un nom
  // technique disparu et seraient rejetées « hors plan » à la finalisation.
  const remapRows = (
    rows: LlmClassementRow[],
    remap: Map<string, string>,
  ): LlmClassementRow[] =>
    remap.size === 0
      ? rows
      : rows.map((r) =>
          r.TargetFolder && remap.has(r.TargetFolder)
            ? { ...r, TargetFolder: remap.get(r.TargetFolder)! }
            : r,
        );

  // Corrections manuelles : re-finalise avec les lignes corrigées.
  const applyCorrections = async (
    rows: LlmClassementRow[],
    validated: CorrectionExample[],
  ) => {
    await refinalize(rows, planValide);
    // Mémorise les corrections de cette passe (cumul par chemin, dernière
    // valeur retenue) pour une éventuelle réinjection few-shot au prochain
    // classement. Capture seulement ; rien n'est envoyé au modèle sans l'opt-in.
    if (validated.length > 0) {
      setCorrections((prev) => mergeCorrections(prev, validated));
    }
  };

  // Création d'un dossier manquant depuis le panneau de rattrapage :
  // l'archiviste ajoute au plan validé le dossier que l'IA n'a pas pu viser (le
  // LLM ne classe que vers des dossiers existants du plan). Réutilise le modèle
  // structuré de l'éditeur d'arborescence (étape audit) ; le plan mis à jour est
  // persisté et repris tel quel par la re-finalisation — le moteur re-dérive
  // l'arbre, seule source de vérité. Renvoie le nom technique du dossier créé.
  // Pas de re-finalisation ici : un dossier vide est exclu du SIP (rien à
  // refléter tant qu'aucun fichier ne lui est rattaché puis appliqué).
  const createPlanFolder = (
    parentTech: string | null,
    title: string,
  ): string | null => {
    const result = addFolderToPlan(planValide, parentTech, title);
    if (!result) return null;
    setPlanValide(result.plan);
    return result.tech;
  };

  // Renomme un dossier créé à cette étape. Renvoie le remap au panneau (pour ses
  // affectations en attente) ET re-finalise les lignes déjà classées réalignées,
  // pour que le rapport de couverture reflète immédiatement le nouveau plan — le
  // dossier peut déjà être matérialisé dans le SIP, hors des `edits` en attente.
  const renamePlanFolder = (
    tech: string,
    title: string,
  ): FolderRename | null => {
    const result = renameFolderInPlan(planValide, tech, title);
    if (!result) return null;
    setPlanValide(result.plan);
    // Fire-and-forget : l'erreur éventuelle est déjà affichée par `refinalize`
    // (setLastError) ; on absorbe la rejection pour ne pas la laisser orpheline.
    if (llmRawRows)
      void refinalize(remapRows(llmRawRows, result.remap), result.plan).catch(
        () => {},
      );
    return result;
  };

  // Supprime un dossier créé à cette étape (et son sous-arbre). Les lignes déjà
  // classées qui le visaient sont retirées (les fichiers redeviennent non
  // classés), les frères décalés réalignés, puis on re-finalise pour que le
  // rapport reflète la suppression. Renvoie le remap + les noms supprimés au
  // panneau (qui dé-affecte ses corrections en attente).
  const deletePlanFolder = (tech: string): FolderDelete | null => {
    const result = deleteFolderFromPlan(planValide, tech);
    if (!result) return null;
    setPlanValide(result.plan);
    if (llmRawRows) {
      const removed = new Set(result.removed);
      const remapped = remapRows(
        llmRawRows.filter(
          (r) => !(r.TargetFolder && removed.has(r.TargetFolder)),
        ),
        result.remap,
      );
      void refinalize(remapped, result.plan).catch(() => {});
    }
    return result;
  };

  // Garde de reprise : un lot est relancé **par index**, et le moteur re-dérive
  // les items à chaque appel. Reprendre un run d'une session antérieure n'a donc
  // de sens que si le corpus préparé est resté le même — les options de
  // préparation sont des réglages globaux, modifiables entre deux sessions.
  // Vérification une seule fois, au premier relancement, par un appel
  // `/classement/prepare` (sans LLM). En cas d'écart, on repart de zéro plutôt
  // que de produire un classement silencieusement décalé.
  const ensureResumeValid = async (): Promise<boolean> => {
    if (!resumeUnverifiedRef.current) return true;
    try {
      const prepResp = await postJson<{ total: number; error?: string }>(
        "/classement/prepare",
        { csv, prep },
      );
      if (prepResp.error) throw new Error(prepResp.error);
      if (!resumeStillValid(batchesRef.current, prepResp.total)) {
        batchesRef.current = [];
        setBatchesState(null);
        setClassementBatches(null);
        setLastError(
          "Le corpus à classer a changé depuis le classement interrompu " +
            "(fichier ou options de préparation) : la reprise lot par lot n'est " +
            "plus fiable. Relancez le classement complet.",
        );
        return false;
      }
    } catch (err) {
      setLastError(formatApiError(err));
      return false;
    }
    resumeUnverifiedRef.current = false;
    return true;
  };

  const retryBatch = async (i: number) => {
    if (!(await ensureResumeValid())) return;
    // Contrôleur neuf : l'ancien peut être resté `aborted` après un « Arrêter »,
    // ce qui ferait échouer la relance instantanément.
    abortControllerRef.current = new AbortController();
    setClassementRunning(true);
    await runSingleBatch(i);
    setClassementRunning(false);
    if (batchesRef.current.every((b) => b.status === "done")) await finalize();
  };

  const retryAllErrored = async () => {
    if (!(await ensureResumeValid())) return;
    abortControllerRef.current = new AbortController();
    const erroredIdx = batchesRef.current.flatMap((b, i) =>
      b.status === "error" ? [i] : [],
    );
    const k = resolveConcurrency(
      classementConcurrency,
      providerMode === "local",
      erroredIdx.length,
    );
    setClassementRunning(true);
    const t0 = nowMs();
    // Le pool itère sur des positions [0, erroredIdx.length) → index réel du lot.
    await runBatchPool(
      erroredIdx.length,
      k,
      (pos) => runSingleBatch(erroredIdx[pos]),
      () => abortControllerRef.current?.signal.aborted ?? false,
    );
    setClassementRunning(false);
    if (batchesRef.current.every((b) => b.status === "done"))
      await finalize(k > 1 ? nowMs() - t0 : undefined);
  };

  const clearBatches = () => {
    batchesRef.current = [];
    setBatchesState(null);
    setClassementBatches(null);
    resumeUnverifiedRef.current = false;
  };

  const stopClassement = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  };

  const timestamp = () =>
    new Date()
      .toISOString()
      .replace("T", "_")
      .replace(/-/g, "")
      .replace(/:/g, "")
      .slice(0, 15);

  // Mise en forme des titres au moment du téléchargement (cf. options d'export
  // dans les Paramètres). Deux transformations indépendantes :
  //  - folderTitleFromFile : pour les dossiers (RecordGrp), remplace le
  //    Content.Title hiérarchique par le nom technique de l'arborescence (File) ;
  //    la racine (File === ".") n'est pas touchée.
  //  - keepOriginalFileTitle : pour les fichiers (Item), rétablit le titre
  //    d'origine du CSV importé (indexé par chemin File) à la place du renommage
  //    proposé par l'IA.
  const applyExportTitleChoices = (rows: SedaRow[]): SedaRow[] => {
    const { folderTitleFromFile, keepOriginalFileTitle } = exportOptions;
    if (!folderTitleFromFile && !keepOriginalFileTitle) return rows;

    const origItemTitle = new Map<string, string>();
    if (keepOriginalFileTitle && csvOriginal) {
      for (const r of csvOriginal) {
        if (r["Content.DescriptionLevel"] === "Item")
          origItemTitle.set(r["File"], r["Content.Title"] ?? "");
      }
    }

    return rows.map((r) => {
      const level = r["Content.DescriptionLevel"];
      if (
        folderTitleFromFile &&
        level === "RecordGrp" &&
        r["File"] &&
        r["File"] !== "."
      )
        return { ...r, "Content.Title": r["File"] };
      if (keepOriginalFileTitle && level === "Item") {
        const orig = origItemTitle.get(r["File"]);
        if (orig) return { ...r, "Content.Title": orig };
      }
      return r;
    });
  };

  const downloadCsv = () => {
    if (!csvFinal) return;
    const csv = stringifyCsv(applyExportTitleChoices(csvFinal.rows), csvFinal.columns);
    // Pas de BOM : Resip rejette le header avec BOM (le ﻿ se colle à "ID")
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `classement_final_${timestamp()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadRowsCsv = (
    rows: LlmClassementRow[] | null,
    suffix: string,
  ) => {
    if (!rows || rows.length === 0) return;
    const csv = stringifyCsv(rows as unknown as Record<string, string>[]);
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `classement_llm_brut${suffix}_${timestamp()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadRawLlmCsv = () => downloadRowsCsv(llmRawRows, "");

  // Journal de traitement — traçabilité réglementaire. Le rendu vit côté
  // moteur (POST /journal, source unique partagée avec la CLI `--journal`) : le
  // front ne fait que rassembler les métadonnées déjà obtenues (modèle, versions
  // de prompt, durées, conformité, anomalies) et télécharger le Markdown produit.
  // Aucune logique métier en TS ; aucun contenu documentaire transmis
  // (`inputName` est un nom de fichier).
  const downloadJournal = async () => {
    if (!csvFinal) return;
    setJournalBusy(true);
    setLastError("");
    try {
      const promptVersions: Record<string, string> = {};
      if (promptVersionAudit) promptVersions["AUD-001"] = promptVersionAudit;
      if (promptVersionClassement)
        promptVersions["CLA-001"] = promptVersionClassement;

      const durationMs =
        (durationAudit ?? 0) + (durationClassementTotal ?? 0);
      const usage = unmapUsage(sumUsage([usageAudit, usageClassementTotal]));

      // Modèle figé *par étape* (et non le réglage courant `modelId`, qui a pu
      // changer depuis) : c'est le cœur de la traçabilité. La carte `models` fait
      // foi côté moteur ; `model` reste renseigné en repli pour un journal mono-modèle.
      const models: Record<string, string> = {};
      if (modelAudit) models["AUD-001"] = modelAudit;
      if (modelClassement) models["CLA-001"] = modelClassement;

      const { markdown } = await postJson<{ markdown: string }>("/journal", {
        // Plan fourni par l'archiviste → aucun audit LLM dans ce run.
        command: planOrigin === "fourni" ? "classement" : "run",
        inputName: csvFilename,
        model: modelAudit ?? modelClassement ?? modelId,
        models,
        promptVersions,
        durationS: durationMs > 0 ? durationMs / 1000 : null,
        rows: csvOriginal.length,
        usage,
        warnings: csvFinal.warnings,
        conformity: csvFinal.stats ?? null,
        descriptionSent: tokenOptions.includeDescription,
        // Traçabilité de l'origine du plan : « audit LLM » vs « fourni », avec
        // ou sans retouches manuelles.
        planOrigin: planOrigin ?? undefined,
        planModified: planModifie,
      });

      const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `journal_traitement_${timestamp()}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setLastError(formatApiError(err));
    } finally {
      setJournalBusy(false);
    }
  };

  // Arborescence modèle — étude préalable avant import RESIP. Le rendu vit
  // côté moteur (POST /manifest, source unique partagée avec la CLI `--manifest`) :
  // le front renvoie les lignes RESIP déjà produites (`csvFinal.rows`, la même
  // forme que `resip.rows` de finalize) et le moteur en dérive l'arborescence de
  // répertoires cible, qu'il rend en Markdown. Aucune logique métier en TS ;
  // aucun contenu documentaire transmis (noms de dossiers, titres et dates seuls).
  const downloadManifest = async () => {
    if (!csvFinal) return;
    setManifestBusy(true);
    setLastError("");
    try {
      const { markdown } = await postJson<{ markdown: string }>("/manifest", {
        rows: csvFinal.rows,
      });

      const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `arborescence_modele_${timestamp()}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setLastError(formatApiError(err));
    } finally {
      setManifestBusy(false);
    }
  };

  // Avis de l'IA. En mode appel-unique : dérivé de la réponse complète, affiché
  // en tête. En mode lot : un avis par lot, rendu dans la zone du lot concerné
  // (`b.preCsv`) — pas ici.
  const preCsvText = extractAvis(llmRawResponse);

  // ── Mesures ─────────────────────────────────────────────────────────────────
  const itemRowsOrig = csvOriginal.filter(
    (r) => r["Content.DescriptionLevel"] === "Item",
  );
  const nOrigItems = itemRowsOrig.length;
  const nNewRg = csvFinal
    ? csvFinal.rows.filter(
        (r) => r["Content.DescriptionLevel"] === "RecordGrp",
      ).length
    : 0;
  const nNewItems = csvFinal
    ? csvFinal.rows.filter((r) => r["Content.DescriptionLevel"] === "Item")
        .length
    : 0;
  const nNoDate = csvFinal
    ? csvFinal.rows.filter(
        (r) =>
          r["Content.DescriptionLevel"] === "Item" &&
          (!r["Content.StartDate"] || r["Content.StartDate"] === ""),
      ).length
    : 0;
  const missing = nOrigItems - nNewItems;
  // Doublons de classement : un même fichier source recopié sur plusieurs
  // lignes LLM → deux lignes Item de même ID à la conversion (rejetées par
  // Resip). Compté ici sur la clé d'identité de la ligne (Path, ou Ref en mode
  // Ref : une Ref identique désigne le même fichier) pour piloter l'ouverture du
  // panneau de rattrapage, où l'archiviste retire les exemplaires superflus.
  const redundantClassements = (() => {
    if (!llmRawRows) return 0;
    const seen = new Map<string, number>();
    for (const r of llmRawRows) {
      const k = r.Path ?? r.Ref ?? "";
      if (k) seen.set(k, (seen.get(k) ?? 0) + 1);
    }
    let redundant = 0;
    for (const c of seen.values()) if (c > 1) redundant += c - 1;
    return redundant;
  })();
  // Travail de rattrapage à proposer : fichiers non classés à rattacher OU
  // exemplaires en double à retirer. Le panneau couvre désormais les deux.
  const hasReclassWork = missing > 0 || redundantClassements > 0;
  const reclassPanelLabel = (() => {
    const parts: string[] = [];
    if (missing > 0) parts.push(`${missing} non classé${plS(missing)}`);
    if (redundantClassements > 0)
      parts.push(
        `${redundantClassements} classé${plS(redundantClassements)} en double`,
      );
    return parts.length > 0
      ? `Corriger le classement — ${parts.join(", ")}`
      : "Corriger le classement";
  })();
  // Avertissements de finalisation. Le backend y inclut le contrôle d'intégrité
  // (validate_output_csv : colonnes, orphelins, racine, cycles, inversions de
  // dates) sous le préfixe « Contrôle d'intégrité : » — séparé ici pour un
  // affichage en alerte distincte. Absent des projets persistés avant son
  // introduction côté backend (→ re-finaliser pour l'obtenir).
  const INTEGRITY_PREFIX = "Contrôle d'intégrité : ";
  const allWarnings = csvFinal?.warnings ?? [];
  const coherenceErrors = allWarnings
    .filter((w) => w.startsWith(INTEGRITY_PREFIX))
    .map((w) => w.slice(INTEGRITY_PREFIX.length));
  const convWarnings = allWarnings.filter(
    (w) => !w.startsWith(INTEGRITY_PREFIX),
  );

  // Conformité au plan et compteurs de qualité : calculés à la source (backend)
  // — on les affiche tels quels. `stats` est absent des projets persistés avant
  // son introduction (→ relancer le classement pour obtenir les indicateurs).
  const stats = csvFinal?.stats;
  // Compteurs lus dans `stats` (jamais re-dérivés des messages texte).
  const nUnknownTarget = stats?.targetsUnknown ?? 0;
  const nAbsentLlm = stats?.itemsUnclassified ?? 0;
  const nExtFixed = stats?.extensionsFixed ?? 0;
  // Triage des anomalies : la catégorisation vit côté moteur
  // (`resip.anomalies`). Repli pour les projets persistés avant son ajout :
  // chaque avertissement de conversion devient une anomalie « autre » (le
  // contrôle d'intégrité est affiché à part, donc exclu).
  const anomalies = csvFinal?.anomalies ?? anomaliesFromWarnings(convWarnings);
  const planEcarts = stats
    ? stats.foldersOffPlan.length + stats.foldersMissing.length
    : 0;

  const csvFinalCols = csvFinal ? Object.keys(csvFinal.rows[0] ?? {}) : [];
  const missingCols = csvFinal
    ? REQUIRED_COLUMNS.filter((c) => !csvFinalCols.includes(c))
    : [];

  return (
    <div className="space-y-4">
      {/* ── Plan summary ──────────────────────────────────────────────── */}
      {planModifie && (
        <Alert>
          <AlertDescription>
            Plan de classement validé et revu par l&apos;utilisateur
          </AlertDescription>
        </Alert>
      )}

      <Accordion type="single" collapsible>
        <AccordionItem value="plan">
          <AccordionTrigger>
            <span className="flex items-center gap-1.5">
              <ListTree className="h-3.5 w-3.5" />
              Consulter le plan validé à l&apos;étape précédente
            </span>
          </AccordionTrigger>
          <AccordionContent>
            <div className="space-y-3 pt-2">
              {folderTreeValid ? (
                <div className="rounded-md border border-(--ink-100) bg-(--paper-50) p-3">
                  <PlanTree planValide={planValide} />
                </div>
              ) : (
                <StreamingMarkdown text={planValide} />
              )}
              <p className="text-xs text-(--ink-500)">
                Le plan peut être modifié à l&apos;étape d&apos;Audit.
              </p>
            </div>
          </AccordionContent>
        </AccordionItem>
      </Accordion>

      {/* ── consignes de classement (ancrées ou de fonds) ─────── */}
      {folderTreeValid && (
        <Accordion
          type="single"
          collapsible
          defaultValue={
            classementDirectives.length > 0 || createdFolders.length > 0
              ? "directives"
              : undefined
          }
        >
          <AccordionItem value="directives">
            <AccordionTrigger>
              <span className="flex items-center gap-1.5">
                <MessageSquarePlus className="h-3.5 w-3.5" />
                Consignes de classement
                {classementDirectives.length > 0 &&
                  ` (${classementDirectives.length})`}
              </span>
            </AccordionTrigger>
            <AccordionContent>
              <div className="pt-2">
                <DirectivesPanel
                  directives={classementDirectives}
                  onChange={setClassementDirectives}
                  folders={directiveFolderOptions}
                  createdFolders={createdFolders}
                />
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      )}

      <Separator />

      {/* ── Launch or results ─────────────────────────────────────────── */}
      {csvFinal === null ? (
        <LaunchSection
          folderTreeValid={folderTreeValid}
          classementRunning={classementRunning}
          lastError={lastError}
          llmRawResponse={llmRawResponse}
          streamThinking={streamThinking}
          streamText={streamText}
          batches={batches}
          concurrency={classementConcurrency}
          isLocal={providerMode === "local"}
          singleProgress={singleProgress}
          corrections={corrections}
          reinjectCorrections={reinjectCorrections}
          onReinjectCorrections={setReinjectCorrections}
          onRun={runClassement}
          onStop={stopClassement}
          onRetryBatch={retryBatch}
          onRetryAll={retryAllErrored}
        />
      ) : missingCols.length > 0 ? (
        <>
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>
              Le CSV produit par le LLM ne respecte pas le format SEDA attendu
            </AlertTitle>
            <AlertDescription>
              <p className="text-sm">
                <strong>Colonnes manquantes :</strong> {missingCols.join(", ")}
              </p>
              <p className="mt-1 text-sm">
                <strong>Colonnes reçues :</strong>{" "}
                {Object.keys(csvFinal!.rows[0] ?? {}).join(", ")}
              </p>
              <p className="mt-2 text-sm">
                Le modèle n&apos;a pas suivi les instructions. Relancez le
                classement ou utilisez un modèle plus performant.
              </p>
              {llmRawResponse && (
                <Accordion type="single" collapsible className="mt-2">
                  <AccordionItem value="raw">
                    <AccordionTrigger>
                      <span className="flex items-center gap-1.5">
                        <FileText className="h-3.5 w-3.5" />
                        Réponse brute du LLM (diagnostic)
                      </span>
                    </AccordionTrigger>
                    <AccordionContent>
                      <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded border border-(--ink-100) bg-(--paper-100) p-2 font-mono text-xs text-(--ink-700)">
                        {llmRawResponse.slice(0, 3000)}
                        {llmRawResponse.length > 3000 ? "…" : ""}
                      </pre>
                    </AccordionContent>
                  </AccordionItem>
                </Accordion>
              )}
            </AlertDescription>
          </Alert>
          <StepActions>
            <Button
              variant="outline"
              size="lg"
              onClick={() => setConfirmRelaunch(true)}
            >
              <RotateCcw className="mr-2 h-4 w-4" />
              Relancer le classement
            </Button>
          </StepActions>
        </>
      ) : (
        <>
          {classementBatches && (
            <Alert>
              <Layers className="h-4 w-4" />
              <AlertDescription>
                Classement produit en{" "}
                <strong>{classementBatches.length} lots</strong>, fusionnés et
                convertis en une seule passe, identifiants et dates cohérents
                sur l&apos;ensemble.
              </AlertDescription>
            </Alert>
          )}

          <h3 className="flex items-center gap-2 text-lg font-semibold text-(--ink-900)">
            <BarChart3 className="h-4 w-4" />
            Rapport de couverture
          </h3>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <Metric label="Dossiers créés" value={nNewRg} />
            <Metric
              label="Items classés"
              value={`${nNewItems} / ${nOrigItems}`}
              delta={missing > 0 ? `-${missing} non classé${plS(missing)}` : undefined}
              deltaKind="bad"
            />
            <Metric
              label="Sans date"
              value={nNoDate}
              delta={nNoDate > 0 ? "À compléter" : undefined}
              deltaKind="bad"
            />
            <Metric
              label="Extensions corrigées"
              value={nExtFixed}
              delta={nExtFixed > 0 ? "Vérifier" : undefined}
              deltaKind="bad"
            />
            <Metric
              label="Respect du plan"
              value={
                !stats
                  ? "—"
                  : !stats.planParsed
                    ? "—"
                    : stats.planMatches
                      ? "Conforme"
                      : `${planEcarts} écart${plS(planEcarts)}`
              }
              delta={
                !stats
                  ? "Relancer le classement"
                  : !stats.planParsed
                    ? "Arborescence du plan illisible"
                    : stats.planMatches
                      ? "Identique au plan d'audit"
                      : `${stats.foldersOffPlan.length} hors plan · ${stats.foldersMissing.length} manquant${plS(stats.foldersMissing.length)}`
              }
              deltaKind={stats?.planMatches ? "good" : "bad"}
            />
          </div>

          {stats &&
            stats.planParsed &&
            (!stats.planMatches || stats.itemsMalformed > 0) && (
              <Alert variant="warning">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>L&apos;arborescence du classement diffère du plan d&apos;audit</AlertTitle>
                <AlertDescription className="space-y-1 text-sm">
                  {stats.foldersOffPlan.length > 0 && (
                    <p className="mb-0!">
                      <strong>Dossiers hors plan</strong> (inventés au classement) :{" "}
                      {stats.foldersOffPlan.join(", ")}
                    </p>
                  )}
                  {stats.foldersMissing.length > 0 && (
                    <p className="mb-0!">
                      <strong>Dossiers du plan non réalisés</strong> (aucun contenu) :{" "}
                      {stats.foldersMissing.join(", ")}
                    </p>
                  )}
                  {stats.itemsMalformed > 0 && (
                    <p className="mb-0!">
                      <strong>{stats.itemsMalformed} fichier{plS(stats.itemsMalformed)} à cible malformée</strong>{" "}
                      (le modèle a indiqué un nom de fichier au lieu d&apos;un
                      dossier) rattaché{plS(stats.itemsMalformed)} à la racine. Voir les avertissements de
                      conversion pour plus de détails.
                    </p>
                  )}
                </AlertDescription>
              </Alert>
            )}

          {missing > 0 && (nAbsentLlm > 0 || nUnknownTarget > 0) && (
            <p className="text-xs text-(--ink-500)">
              Détail des non classés :{" "}
              {[
                nAbsentLlm > 0
                  ? `${nAbsentLlm} absent${plS(nAbsentLlm)} de la sortie LLM`
                  : null,
                nUnknownTarget > 0
                  ? `${nUnknownTarget} avec dossier cible inconnu`
                  : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}

          {/* ── Rattrapage des non-classés (recentré) ────────────────────
              Seule retouche que se réserve ODACEA : rattacher au plan les items
              que l'IA a omis (sinon orphelins à la racine de l'export). Affiché
              uniquement s'il en reste — la retouche des items déjà classés
              relève de Resip, vers lequel ODACEA n'est qu'un passage. Le panneau
              ouvre par défaut sur les seuls problèmes (toggle désactivable) :
              fichiers non classés à rattacher et fichiers classés en double dont
              il faut retirer les exemplaires superflus. */}
          {llmRawRows && llmRawRows.length > 0 && hasReclassWork && (
            <Accordion
              type="single"
              collapsible
              id="reclass-panel"
              value={reclassAccordion}
              onValueChange={setReclassAccordion}
            >
              <AccordionItem value="reclass">
                <AccordionTrigger>
                  <span className="flex items-center gap-1.5">
                    <Pencil className="h-3.5 w-3.5" />
                    {reclassPanelLabel}
                  </span>
                </AccordionTrigger>
                <AccordionContent>
                  <div className="space-y-2 pt-2">
                    {lastError && (
                      <Alert variant="destructive">
                        <AlertCircle className="h-4 w-4" />
                        <AlertDescription className="text-xs whitespace-pre-line">
                          {lastError}
                        </AlertDescription>
                      </Alert>
                    )}
                    <ReclassPanel
                      csvOriginal={csvOriginal}
                      planValide={planValide}
                      llmRawRows={llmRawRows}
                      busy={reclassBusy}
                      onApply={applyCorrections}
                      planOriginal={planValideOriginal}
                      onCreateFolder={createPlanFolder}
                      onRenameFolder={renamePlanFolder}
                      onDeleteFolder={deletePlanFolder}
                      initialSearch={reclassSearch}
                    />
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          )}

          {nNoDate > 0 && (
            <Alert variant="warning">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>
                {nNoDate} Item{plS(nNoDate)} sans date. Vérifiez les champs
                StartDate/EndDate dans le CSV final.
              </AlertDescription>
            </Alert>
          )}

          {coherenceErrors.length > 0 && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Problèmes de cohérence détectés</AlertTitle>
              <AlertDescription>
                <ul className="list-inside list-disc text-sm">
                  {coherenceErrors.map((err, i) => (
                    <li key={i}>{err}</li>
                  ))}
                </ul>
              </AlertDescription>
            </Alert>
          )}

          {/* ── Triage des anomalies : groupées, filtrables, reliées
                 au panneau de correction. ─────────────────────────── */}
          {anomalies.length > 0 && (
            <Accordion type="single" collapsible>
              <AccordionItem value="warns">
                <AccordionTrigger>
                  <span className="flex items-center gap-1.5">
                    <AlertTriangle className="h-3.5 w-3.5 text-(--warning-500)" />
                    {anomalies.length} anomalie{plS(anomalies.length)} de conversion
                  </span>
                </AccordionTrigger>
                <AccordionContent>
                  <div className="pt-2">
                    <AnomaliesTable
                      anomalies={anomalies}
                      onLocate={
                        llmRawRows && llmRawRows.length > 0 && hasReclassWork
                          ? locateItem
                          : undefined
                      }
                    />
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          )}

          <Separator />

          {/* ── Pour aller plus loin (avancé) — replié par défaut ─────────────
              Vérification et diagnostic regroupés pour l'expert, sans alourdir la
              vue par défaut destinée à l'archiviste. Rien n'est retiré : tout
              reste atteignable, simplement replié. ─────────────────────────── */}
          <p className="text-xs font-medium tracking-wide text-(--ink-400) uppercase">
            Pour aller plus loin
          </p>

          <Accordion type="single" collapsible>
            <AccordionItem value="apercu-final">
              <AccordionTrigger>
                <span className="flex items-center gap-1.5">
                  <FileText className="h-3.5 w-3.5" />
                  Aperçu du CSV final ({csvFinal.rows.length} lignes ·{" "}
                  {csvFinal.columns.length} colonnes)
                </span>
              </AccordionTrigger>
              <AccordionContent>
                <div className="space-y-1 pt-2">
                  <p className="text-xs text-(--ink-500)">
                    Aperçu des 20 premières lignes seulement.
                  </p>
                  <CsvPreview
                    rows={applyExportTitleChoices(csvFinal.rows)}
                    maxRows={20}
                  />
                </div>
              </AccordionContent>
            </AccordionItem>
          </Accordion>

          {!classementBatches && preCsvText && (
            <Accordion type="single" collapsible>
              <AccordionItem value="demarche">
                <AccordionTrigger>
                  <span className="flex items-center gap-1.5">
                    <StickyNote className="h-3.5 w-3.5" />
                    Démarche de l&apos;IA
                  </span>
                </AccordionTrigger>
                <AccordionContent>
                  <div className="pt-2">
                    <StreamingMarkdown text={preCsvText} />
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          )}

          {thinkingClassement && <ThinkingPanel thinking={thinkingClassement} />}

          {llmRawRows && llmRawRows.length > 0 && (
            <Accordion type="single" collapsible>
              <AccordionItem value="debug">
                <AccordionTrigger>
                  <span className="flex items-center gap-1.5">
                    <Search className="h-3.5 w-3.5" />
                    {classementBatches
                      ? `CSV brut de l'IA par lot (${classementBatches.length})`
                      : "CSV brut de l'IA (avant conversion)"}
                  </span>
                </AccordionTrigger>
                <AccordionContent>
                  {classementBatches ? (
                    <div className="space-y-3 pt-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={downloadRawLlmCsv}
                      >
                        <Download className="mr-1 h-3.5 w-3.5" />
                        Télécharger le CSV brut complet ({llmRawRows.length}{" "}
                        lignes)
                      </Button>
                      {classementBatches.map((b, i) => (
                        <div
                          key={i}
                          className="space-y-1.5 rounded-md border border-(--ink-100) p-2"
                        >
                          <p className="text-xs font-medium text-(--ink-700)">
                            Lot {i + 1} / {classementBatches.length} —{" "}
                            {b.itemCount} item{plS(b.itemCount)} envoyé{plS(b.itemCount)} · {b.rows.length}{" "}
                            ligne{plS(b.rows.length)} produite{plS(b.rows.length)}
                          </p>
                          {(b.preCsv ?? "").trim() && (
                            <Accordion
                              type="single"
                              collapsible
                              className="border-none bg-transparent px-0"
                            >
                              <AccordionItem value="demarche">
                                <AccordionTrigger className="py-1 text-xs font-medium text-(--ink-600)">
                                  <span className="flex items-center gap-1.5">
                                    <StickyNote className="h-3 w-3" />
                                    Démarche de l&apos;IA
                                  </span>
                                </AccordionTrigger>
                                <AccordionContent className="pb-1 text-xs">
                                  <StreamingMarkdown
                                    text={(b.preCsv ?? "").trim()}
                                  />
                                </AccordionContent>
                              </AccordionItem>
                            </Accordion>
                          )}
                          {b.rows.length > 0 ? (
                            <>
                              <CsvPreview
                                rows={
                                  b.rows as unknown as Record<string, string>[]
                                }
                                maxRows={10}
                              />
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() =>
                                  downloadRowsCsv(b.rows, `_lot${i + 1}`)
                                }
                              >
                                <Download className="mr-1 h-3.5 w-3.5" />
                                Télécharger ce lot
                              </Button>
                            </>
                          ) : (
                            <p className="text-xs text-(--ink-500)">
                              Aucune ligne produite pour ce lot.
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="space-y-2 pt-2">
                      <CsvPreview
                        rows={llmRawRows as unknown as Record<string, string>[]}
                        maxRows={20}
                      />
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={downloadRawLlmCsv}
                      >
                        <Download className="mr-1 h-3.5 w-3.5" />
                        Télécharger le CSV brut IA
                      </Button>
                    </div>
                  )}
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          )}

          {(usageClassementTotal ||
            usageAudit ||
            durationClassementTotal ||
            durationAudit) && (
            <div className="space-y-0.5">
              <TokenUsageBar usage={usageClassementTotal} durationMs={durationClassementTotal} label="CLA-001" model={modelClassement} />
              {((usageAudit && usageClassementTotal) || (durationAudit && durationClassementTotal)) && (
                <p className="text-xs font-medium text-(--ink-500)">
                  {(() => {
                    const segments: string[] = [];
                    if (usageAudit && usageClassementTotal) {
                      const total = sumUsage([usageAudit, usageClassementTotal]);
                      if (total?.totalTokens)
                        segments.push(`${(total.totalTokens / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} k tokens`);
                    }
                    if (durationAudit && durationClassementTotal)
                      segments.push(`traité en ${formatDuration(durationAudit + durationClassementTotal)}`);
                    return `Total session — ${segments.join(". ")}`;
                  })()}
                </p>
              )}
            </div>
          )}

          {/* — application physique du classement : copie du SIP produit
              vers une arborescence cible (la source n'est jamais mutée). Backend
              local uniquement : l'endpoint /apply est refusé en démonstration. */}
          {!DEMO_MODE && csvFinal.rows.length > 0 && (
            <ApplyPanel rows={applyExportTitleChoices(csvFinal.rows)} />
          )}

          {/* CTA de l'étape + relance. La navigation entre étapes passe par le
              fil d'Ariane ; la remise à zéro par « Nouveau projet » (sidebar). */}
          <StepActions>
            <Button onClick={downloadCsv} size="lg">
              <Download className="mr-2 h-4 w-4" />
              Télécharger le CSV final
            </Button>
            {/* Arborescence (visualisation interactive) : confirmation visuelle du
                résultat — gardée visible, c'est le repère le plus parlant pour un
                archiviste. */}
            <Button
              variant="outline"
              onClick={() => setArborescenceOpen(true)}
            >
              <ListTree className="mr-2 h-4 w-4" />
              Arborescence
            </Button>
            {/* Exports fichier secondaires regroupés (allègement du pied) : PDF (D6),
                journal de traitement, arborescence modèle. Tous rendus
                par le moteur à partir de métadonnées seules. Le spinner du
                déclencheur signale l'export en cours, la liste étant alors fermée. */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  disabled={journalBusy || manifestBusy}
                >
                  {journalBusy || manifestBusy ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Download className="mr-2 h-4 w-4" />
                  )}
                  Exporter
                  <ChevronDown className="ml-2 h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => window.print()}>
                  <Printer className="h-4 w-4" />
                  Exporter en PDF
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={downloadJournal}
                  disabled={journalBusy}
                >
                  <FileText className="h-4 w-4" />
                  Journal de traitement
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={downloadManifest}
                  disabled={manifestBusy}
                >
                  <FolderTree className="h-4 w-4" />
                  Arborescence modèle
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <IconAction
              label="Relancer le classement"
              icon={RotateCcw}
              onClick={() => setConfirmRelaunch(true)}
            />
          </StepActions>
        </>
      )}

      <ConfirmDialog
        open={confirmRelaunch}
        onOpenChange={setConfirmRelaunch}
        title="Relancer le classement ?"
        description="Le classement actuel (réponse LLM brute et CSV final) sera supprimé. Le plan validé, l'audit et le CSV importé sont conservés."
        confirmLabel="Relancer"
        destructive
        onConfirm={() => {
          clearBatches();
          setClassementResult("", "", null, null);
        }}
      />

      {csvFinal && (
        <ArborescenceModal
          open={arborescenceOpen}
          onOpenChange={setArborescenceOpen}
          csvOriginal={csvOriginal}
          csvFinal={csvFinal}
        />
      )}
    </div>
  );
}

function LaunchSection({
  folderTreeValid,
  classementRunning,
  lastError,
  llmRawResponse,
  streamThinking,
  streamText,
  batches,
  concurrency,
  isLocal,
  singleProgress,
  corrections,
  reinjectCorrections,
  onReinjectCorrections,
  onRun,
  onStop,
  onRetryBatch,
  onRetryAll,
}: {
  folderTreeValid: boolean;
  classementRunning: boolean;
  lastError: string;
  llmRawResponse: string;
  streamThinking: string;
  streamText: string;
  batches: BatchState[] | null;
  concurrency: number;
  isLocal: boolean;
  singleProgress: { done: number; total: number } | null;
  corrections: CorrectionExample[];
  reinjectCorrections: boolean;
  onReinjectCorrections: (b: boolean) => void;
  onRun: () => void;
  onStop: () => void;
  onRetryBatch: (i: number) => void;
  onRetryAll: () => void;
}) {
  const isBatched = batches !== null;
  const total = batches?.length ?? 0; // nombre de lots (en-têtes de volets)
  // Concurrence effectivement appliquée — sert à l'affichage (« K en
  // parallèle ») et à décider du suivi automatique de l'accordéon.
  const k = resolveConcurrency(concurrency, isLocal, total);
  const erroredIdx =
    batches?.flatMap((b, i) => (b.status === "error" ? [i] : [])) ?? [];

  // Accordéon contrôlé : en séquentiel (k=1), suit automatiquement le lot en
  // cours (ouverture au démarrage, fermeture quand le suivant démarre). En
  // parallèle (k>1), plusieurs lots sont actifs en même temps : le suivi
  // automatique serait sautillant, on laisse l'accordéon sous contrôle manuel
  // (les icônes de statut et la barre de progression suffisent au repérage).
  const runningIdx =
    k > 1 ? -1 : batches?.findIndex((b) => b.status === "running") ?? -1;
  const [openBatch, setOpenBatch] = useState<string | undefined>(undefined);
  // Ajuste l'état pendant le rendu (pattern React) plutôt que dans un effet :
  // quand un nouveau lot démarre, on l'ouvre ; l'utilisateur garde la main.
  const [prevRunning, setPrevRunning] = useState(runningIdx);
  if (runningIdx !== prevRunning) {
    setPrevRunning(runningIdx);
    if (runningIdx >= 0) setOpenBatch(`batch-${runningIdx}`);
  }

  if (!folderTreeValid) {
    return (
      <Alert variant="destructive">
        <XCircle className="h-4 w-4" />
        <AlertTitle>Arborescence technique invalide</AlertTitle>
        <AlertDescription>
          Arborescence technique absente ou invalide. Retournez à
          l&apos;audit pour relancer, ou corrigez le plan dans le panneau
          ci-dessus.
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-3">
      <Alert>
        <AlertDescription>
          Le classement va reclasser virtuellement chaque fichier selon le plan
          validé et produire un CSV SEDA restructuré. Cette étape peut prendre
          plusieurs minutes selon la taille du vrac.
        </AlertDescription>
      </Alert>

      {lastError && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Erreur</AlertTitle>
          <AlertDescription>
            <p className="text-xs whitespace-pre-line">{lastError}</p>
            {llmRawResponse && (
              <Accordion type="single" collapsible className="mt-2">
                <AccordionItem value="raw">
                  <AccordionTrigger>
                    <span className="flex items-center gap-1.5">
                      <FileText className="h-3.5 w-3.5" />
                      Réponse brute du LLM (diagnostic)
                    </span>
                  </AccordionTrigger>
                  <AccordionContent>
                    <p className="text-xs text-(--ink-500)">
                      Le LLM a bien répondu, mais sa sortie n&apos;a pas pu être
                      convertie en CSV RESIP. Vérifiez ci-dessous si le travail
                      est exploitable, sinon relancez.
                    </p>
                    <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded border border-(--ink-100) bg-(--paper-100) p-2 font-mono text-xs text-(--ink-700)">
                      {llmRawResponse.slice(0, 5000)}
                      {llmRawResponse.length > 5000 ? "…" : ""}
                    </pre>
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
            )}
          </AlertDescription>
        </Alert>
      )}

      {isBatched ? (
        <div className="space-y-3">
          <Alert>
            <Layers className="h-4 w-4" />
            <AlertTitle>Mode traitement par lot activé</AlertTitle>
            <AlertDescription>
              Le nombre d&apos;items dépasse le seuil configuré : le classement
              est découpé en <strong>{total} lots</strong>&nbsp;
              {k > 1 ? (
                <>
                  traités <strong>jusqu&apos;à {k} en parallèle</strong>
                </>
              ) : (
                "traités successivement"
              )}
              . Chaque lot reçoit le plan validé complet ; les résultats sont
              ensuite fusionnés et convertis en une seule passe pour garantir un
              classement cohérent sur l&apos;ensemble.
            </AlertDescription>
          </Alert>
          <BatchProgressBar batches={batches!} />

          {/* Un volet par lot : se déplie automatiquement pendant le traitement
              (streaming live), se replie une fois terminé. */}
          <Accordion
            type="single"
            collapsible
            value={openBatch}
            onValueChange={setOpenBatch}
          >
            {batches!.map((b, i) => (
              <AccordionItem value={`batch-${i}`} key={i}>
                <AccordionTrigger>
                  <span className="flex items-center gap-2">
                    <BatchStatusIcon status={b.status} />
                    <span>
                      Lot {i + 1} / {total} — {b.itemCount} item{plS(b.itemCount)}
                      {b.status === "done" &&
                        ` · ${b.rows.length} ligne${plS(b.rows.length)} produite${plS(b.rows.length)}`}
                      {b.status === "running" && " · en cours…"}
                      {b.status === "error" && " · erreur"}
                    </span>
                  </span>
                </AccordionTrigger>
                <AccordionContent>
                  <div className="space-y-2 pt-1">
                    {b.status === "error" && b.error && (
                      <p className="text-xs whitespace-pre-line text-(--danger-500)">{b.error}</p>
                    )}
                    {b.thinking && (
                      <ThinkingPanel thinking={b.thinking} defaultOpen />
                    )}
                    {b.rawText ? (
                      <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md border border-(--ink-100) bg-(--paper-100) p-3 font-mono text-xs text-(--ink-700)">
                        {b.rawText}
                      </pre>
                    ) : (
                      b.status !== "error" && (
                        <p className="text-sm text-(--ink-500)">
                          {b.status === "running"
                            ? "En attente de la réponse du modèle…"
                            : "Lot en attente de traitement."}
                        </p>
                      )
                    )}
                  </div>
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>

          {erroredIdx.length > 0 && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>{erroredIdx.length} lot{plS(erroredIdx.length)} en erreur</AlertTitle>
              <AlertDescription>
                <ul className="space-y-1.5 text-xs">
                  {erroredIdx.map((i) => (
                    <li
                      key={i}
                      className="flex items-center justify-between gap-2"
                    >
                      <span>
                        Lot {i + 1} : {batches![i].error}
                      </span>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={classementRunning}
                        onClick={() => onRetryBatch(i)}
                      >
                        <RotateCcw className="mr-1 h-3.5 w-3.5" />
                        Relancer ce lot
                      </Button>
                    </li>
                  ))}
                </ul>
                {erroredIdx.length > 1 && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-2 w-full"
                    disabled={classementRunning}
                    onClick={onRetryAll}
                  >
                    <RotateCcw className="mr-1 h-3.5 w-3.5" />
                    Relancer tous les lots en erreur
                  </Button>
                )}
              </AlertDescription>
            </Alert>
          )}
        </div>
      ) : (
        classementRunning && (
          <>
            {singleProgress && (
              <ItemProgressBar
                done={singleProgress.done}
                total={singleProgress.total}
              />
            )}
            {!streamThinking && !streamText && (
              <p role="status" aria-live="polite" className="text-sm text-(--ink-500)">
                En attente de la réponse du modèle…
              </p>
            )}
            {streamThinking && (
              <ThinkingPanel thinking={streamThinking} defaultOpen />
            )}
            {streamText && (
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md border border-(--ink-100) bg-(--paper-100) p-3 font-mono text-xs text-(--ink-700)">
                {streamText}
              </pre>
            )}
          </>
        )
      )}

      {/* ── Apprentissage des corrections (opt-in, expérimental) ──────
          Visible seulement après une correction dans cette session. Réinjecte
          les corrections validées comme exemples few-shot au prochain classement
          (« appliquer la même logique »). ⚠️ Modifie le prompt CLA-001 :
          efficacité à valider sur modèles réels — désactivé par défaut. */}
      {corrections.length > 0 && (
        <div className="rounded-md border border-(--ink-100) bg-(--paper-100) p-3">
          <div className="flex items-start gap-2.5">
            <Switch
              id="reinject-corrections"
              checked={reinjectCorrections}
              onCheckedChange={onReinjectCorrections}
              disabled={classementRunning}
              className="mt-0.5"
            />
            <div className="space-y-1">
              <Label
                htmlFor="reinject-corrections"
                className="cursor-pointer text-sm font-medium"
              >
                {corrections.length === 1
                  ? "Réutiliser ma correction comme exemple (expérimental)"
                  : `Réutiliser mes ${corrections.length} corrections comme exemples (expérimental)`}
              </Label>
              <p className="text-xs text-(--ink-500)">
                Les fichiers que vous avez reclassés à la main sont transmis au
                modèle comme exemples (chemin → dossier cible) pour qu&apos;il
                applique la même logique au reste du vrac. N&apos;envoie que des
                métadonnées (jamais le contenu). Modifie la consigne envoyée au
                modèle : à n&apos;activer que si des erreurs reviennent souvent.
              </p>
            </div>
          </div>
        </div>
      )}

      <StepActions>
        <Button onClick={onRun} disabled={classementRunning} size="lg">
          {classementRunning ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Classement en cours…
            </>
          ) : (
            "Lancer le classement"
          )}
        </Button>
        {classementRunning && (
          <Button onClick={onStop} variant="destructiveGhost" size="lg">
            <CircleStop className="mr-2 h-4 w-4" />
            Arrêter
          </Button>
        )}
      </StepActions>
    </div>
  );
}

function ItemProgressBar({
  done,
  total,
}: {
  done: number;
  total: number;
}) {
  // Estimation live : bornée à [0, total]. Le compte affiché est plafonné au
  // total (le LLM peut produire plus de lignes que d'items en cours de flux).
  const shown = Math.min(done, total);
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-(--ink-500)">
        <span>
          {shown} / {total} fichier{plS(total)} classé{plS(total)}
        </span>
        <span>{pct}%</span>
      </div>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={shown}
        aria-label={`${shown} sur ${total} fichiers classés`}
        className="relative h-2 w-full overflow-hidden rounded-full bg-(--ink-100)"
      >
        <div
          className="h-full bg-(--ink-700) transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/** Barre de progression du mode lot : **un segment par lot** (largeur ∝ nombre
 *  d'items), chacun rempli selon *sa propre* avancée et coloré par son statut.
 *  Contrairement à une barre agrégée qui se remplit de gauche à droite (et
 *  suggère un traitement séquentiel), plusieurs segments progressent de front en
 *  mode parallèle — le rendu reflète alors fidèlement les lots simultanés. En
 *  séquentiel, les segments se remplissent l'un après l'autre. */
function BatchProgressBar({ batches }: { batches: BatchState[] }) {
  const totalItems = batches.reduce((s, b) => s + b.itemCount, 0);
  const itemsDone = batches.reduce(
    (s, b) => s + (b.status === "done" ? b.rows.length : b.liveCount ?? 0),
    0,
  );
  const shown = Math.min(itemsDone, totalItems);
  const pct =
    totalItems > 0 ? Math.min(100, Math.round((itemsDone / totalItems) * 100)) : 0;
  const nDone = batches.filter((b) => b.status === "done").length;
  const nRunning = batches.filter((b) => b.status === "running").length;
  const nError = batches.filter((b) => b.status === "error").length;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-(--ink-500)">
        <span>
          {shown} / {totalItems} fichier{plS(totalItems)} classé{plS(totalItems)}
        </span>
        <span>{pct}%</span>
      </div>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={totalItems}
        aria-valuenow={shown}
        aria-label={`${shown} sur ${totalItems} fichiers classés`}
        className="flex h-2 w-full gap-px overflow-hidden rounded-full"
      >
        {batches.map((b, i) => {
          const frac =
            b.status === "done"
              ? 1
              : b.status === "running"
                ? Math.min(1, (b.liveCount ?? 0) / Math.max(1, b.itemCount))
                : 0;
          const fill =
            b.status === "error"
              ? "bg-(--danger-500)"
              : b.status === "done"
                ? "bg-(--success-500)"
                : "bg-(--ink-700)";
          return (
            <div
              key={i}
              className="relative h-full overflow-hidden bg-(--ink-100) first:rounded-l-full last:rounded-r-full"
              style={{ flexGrow: b.itemCount, flexBasis: 0 }}
              title={`Lot ${i + 1} : ${b.itemCount} item${plS(b.itemCount)}`}
            >
              <div
                className={`h-full transition-all ${fill} ${b.status === "error" ? "w-full" : ""}`}
                style={b.status === "error" ? undefined : { width: `${frac * 100}%` }}
              />
            </div>
          );
        })}
      </div>
      {/* Décompte par statut — donne la mesure de l'activité simultanée. */}
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-(--ink-500)">
        <span>
          {nDone} / {batches.length} lot{plS(batches.length)} terminé{plS(nDone)}
        </span>
        {nRunning > 0 && (
          <span className="text-(--ink-700)">{nRunning} en cours</span>
        )}
        {nError > 0 && (
          <span className="text-(--danger-500)">
            {nError} en erreur
          </span>
        )}
      </div>
    </div>
  );
}

function BatchStatusIcon({ status }: { status: BatchState["status"] }) {
  switch (status) {
    case "running":
      return <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-(--ink-700)" />;
    case "done":
      return <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-(--success-500)" />;
    case "error":
      return <AlertCircle className="h-3.5 w-3.5 shrink-0 text-(--danger-500)" />;
    default:
      return <Circle className="h-3.5 w-3.5 shrink-0 text-(--ink-300)" />;
  }
}

function Metric({
  label,
  value,
  delta,
  deltaKind,
}: {
  label: string;
  value: number | string;
  delta?: string;
  deltaKind?: "good" | "bad";
}) {
  return (
    <div className="rounded-md border border-(--ink-100) bg-(--paper-50) p-3">
      <div className="text-xs text-(--ink-500)">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-(--ink-900)">{value}</div>
      {delta && (
        <div
          className={
            "mt-0.5 text-xs " +
            (deltaKind === "bad" ? "text-(--danger-500)" : "text-(--success-500)")
          }
        >
          {delta}
        </div>
      )}
    </div>
  );
}
