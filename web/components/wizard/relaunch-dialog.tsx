"use client";

import { useState } from "react";
import type { ResipStats, RevisionTurn } from "@/lib/csv/types";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { History, Info, RotateCcw, Sparkles } from "lucide-react";

/** Branche retenue par l'archiviste. */
export type RelaunchMode = "identique" | "revision";

/**
 * Dialogue de relance du classement. Deux branches :
 *
 * - **à l'identique** — le classement est refait de zéro avec les mêmes réglages
 *   (comportement historique) ;
 * - **avec consignes de révision** — le modèle reçoit *son propre classement
 *   précédent* et ce qu'il faut y corriger. C'est une conversation dont l'état
 *   remplace le transcript : les décisions précédentes voyagent ligne à ligne
 *   avec chaque lot (coût proportionnel au lot, pas au fonds) et le préfixe
 *   stable ne porte que les consignes + une synthèse mesurée du run précédent.
 *
 * Les deux branches **lancent** le classement : le geste est complet en une
 * validation. Présentation pure — la mise en forme du canal vit dans le
 * moteur (`core.cla_revision`) ; ce composant collecte une consigne et affiche ce
 * que le modèle recevra.
 */
export function RelaunchDialog({
  open,
  onOpenChange,
  onRelaunch,
  canRevise,
  previousItemCount,
  previousStats,
  turns,
  batchSize,
  correctionCount,
  reinjectCorrections,
  onReinjectCorrections,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Lance le classement dans la branche choisie (consigne vide si « identique »). */
  onRelaunch: (mode: RelaunchMode, consigne: string) => void;
  /** Un classement exploitable existe-t-il pour servir de base à la révision ? */
  canRevise: boolean;
  /** Nombre de décisions du tour précédent (reportées ligne à ligne). */
  previousItemCount: number;
  /** Stats du run précédent — la synthèse que le moteur enverra au modèle. */
  previousStats: ResipStats | null;
  /** Consignes des tours déjà joués (acquises, réinjectées avec la nouvelle). */
  turns: RevisionTurn[];
  /** Taille de lot réglée — sert à situer le surcoût d'un lot de révision. */
  batchSize: number;
  /** Corrections manuelles disponibles pour le few-shot. */
  correctionCount: number;
  reinjectCorrections: boolean;
  onReinjectCorrections: (b: boolean) => void;
}) {
  const [mode, setMode] = useState<RelaunchMode>(canRevise ? "revision" : "identique");
  const [consigne, setConsigne] = useState("");

  // Réouverture : on repart d'une consigne vierge (un tour de révision n'est pas
  // un brouillon qu'on retrouve) et de la branche la plus utile. Ajusté pendant
  // le rendu (pattern React) plutôt que dans un effet, qui déclencherait un
  // rendu en cascade.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setConsigne("");
      setMode(canRevise ? "revision" : "identique");
    }
  }

  const submit = () => {
    onRelaunch(mode, mode === "revision" ? consigne.trim() : "");
    onOpenChange(false);
  };

  const missing = previousStats?.foldersMissing?.length ?? 0;
  const offPlan = previousStats?.foldersOffPlan?.length ?? 0;
  const unclassified = previousStats?.itemsUnclassified ?? 0;
  const malformed = previousStats?.itemsMalformed ?? 0;
  // Ce que la synthèse dira au modèle — mêmes chiffres que ceux déjà affichés
  // dans les résultats, pour qu'il n'y ait pas deux vérités à l'écran.
  const facts = [
    missing > 0 && `${missing} dossier(s) du plan resté(s) vides`,
    offPlan > 0 && `${offPlan} dossier(s) hors plan`,
    unclassified > 0 && `${unclassified} fichier(s) non classé(s)`,
    malformed > 0 && `${malformed} cible(s) malformée(s)`,
  ].filter(Boolean) as string[];

  // Une révision sans consigne n'a rien à corriger : le bouton reste inactif.
  const disabled = mode === "revision" && consigne.trim().length === 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Relancer le classement</DialogTitle>
          <DialogDescription>
            Le classement actuel (réponse LLM brute et CSV final) sera remplacé.
            Le plan validé, l&apos;audit et le CSV importé sont conservés.
          </DialogDescription>
        </DialogHeader>

        <Tabs value={mode} onValueChange={(v) => setMode(v as RelaunchMode)}>
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="revision" disabled={!canRevise}>
              <Sparkles className="mr-1.5 h-3.5 w-3.5" />
              Avec consignes de révision
            </TabsTrigger>
            <TabsTrigger value="identique">
              <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
              À l&apos;identique
            </TabsTrigger>
          </TabsList>

          {/* ── Révision ────────────────────────────────────────────────── */}
          <TabsContent value="revision" className="space-y-3 pt-3">
            <div className="space-y-1.5">
              <Label htmlFor="revision-consigne">Ce qu&apos;il faut corriger</Label>
              <Textarea
                id="revision-consigne"
                value={consigne}
                onChange={(e) => setConsigne(e.target.value)}
                rows={4}
                autoFocus
                placeholder={
                  "Ex. : les CV et lettres de motivation vont dans 1-2, pas dans 1-1.\n" +
                  "Ne pas mettre de date en tête des noms de fichiers."
                }
              />
              <p className="text-xs text-(--ink-500)">
                Le modèle reçoit son classement précédent et ne modifie que ce que
                vos consignes impliquent — le reste est conservé à l&apos;identique.
              </p>
            </div>

            {turns.length > 0 && (
              <div className="space-y-1.5">
                <p className="flex items-center gap-1.5 text-xs font-medium text-(--ink-700)">
                  <History className="h-3.5 w-3.5" />
                  Consignes des tours précédents ({turns.length}) — toujours en vigueur
                </p>
                <ul className="space-y-1 rounded border border-(--ink-100) bg-(--paper-100) p-2 text-xs text-(--ink-700)">
                  {turns.map((t, i) => (
                    <li key={`${t.at}-${i}`}>• {t.consigne}</li>
                  ))}
                </ul>
              </div>
            )}

            <Alert>
              <Info className="h-4 w-4" />
              <AlertDescription className="text-xs">
                <p className="font-medium text-(--ink-700)">
                  Ce que le modèle recevra
                </p>
                <ul className="mt-1 space-y-0.5">
                  <li>
                    • vos {turns.length + 1} consigne(s) de révision ;
                  </li>
                  <li>
                    • ses {previousItemCount} décision(s) précédentes, reportées
                    ligne à ligne (colonnes <code>PrevFolder</code> /{" "}
                    <code>PrevTitle</code>) ;
                  </li>
                  <li>
                    •{" "}
                    {facts.length > 0
                      ? `la synthèse du run précédent : ${facts.join(", ")}.`
                      : "la synthèse du run précédent (volumétrie et conformité)."}
                  </li>
                </ul>
                <p className="mt-1.5">
                  Un lot de révision est plus volumineux qu&apos;un lot normal (deux
                  colonnes de plus par fichier). Si le modèle a une petite fenêtre de
                  contexte, réduisez la taille de lot dans Paramètres (actuellement{" "}
                  {batchSize}).
                </p>
              </AlertDescription>
            </Alert>
          </TabsContent>

          {/* ── À l'identique ───────────────────────────────────────────── */}
          <TabsContent value="identique" className="pt-3">
            <p className="text-sm text-(--ink-700)">
              Le classement est refait <strong>de zéro</strong>, avec les mêmes
              réglages (modèle, méthode d&apos;identifiant, taille de lot) et les
              mêmes consignes de classement. Le modèle ne voit pas son résultat
              précédent : il peut aussi bien corriger que défaire ce qui allait.
            </p>
            {turns.length > 0 && (
              <p className="mt-2 text-xs text-(--ink-500)">
                Les {turns.length} consigne(s) de révision déjà données seront
                oubliées.
              </p>
            )}
          </TabsContent>
        </Tabs>

        {/* s'applique aux deux branches : la relance étant désormais d'un
            seul geste, l'opt-in doit vivre ici, sinon l'écran de lancement qui le
            portait n'est plus traversé. */}
        {correctionCount > 0 && (
          <div className="flex items-start gap-2 rounded border border-(--ink-100) bg-(--paper-100) p-2">
            <Switch
              id="reinject-corrections"
              checked={reinjectCorrections}
              onCheckedChange={onReinjectCorrections}
            />
            <Label htmlFor="reinject-corrections" className="text-xs font-normal">
              Réutiliser mes {correctionCount} correction(s) manuelle(s) comme
              exemples
              <span className="block text-(--ink-500)">
                Le modèle voit des classements que vous avez validés et applique la
                même logique aux fichiers similaires.
              </span>
            </Label>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Annuler
          </Button>
          <Button onClick={submit} disabled={disabled}>
            {mode === "revision" ? "Réviser le classement" : "Relancer à l'identique"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
