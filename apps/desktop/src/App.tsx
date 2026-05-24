import {
  Activity,
  AlertTriangle,
  Clipboard,
  Cpu,
  Database,
  Download,
  EyeOff,
  FileText,
  Gauge,
  History,
  LockKeyhole,
  Pause,
  Play,
  RefreshCw,
  ScrollText,
  Server,
  Settings,
  ShieldCheck,
  Square,
  Trash2
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

const API_BASE = window.watcher?.apiBase ?? "http://127.0.0.1:8765/api";

type View = "dashboard" | "session" | "notes" | "history" | "runtime" | "privacy" | "exports" | "diagnostics";

type Session = {
  id: string;
  objective: string;
  status: "active" | "paused" | "stopped";
  started_at: string;
  ended_at?: string;
  capture_interval_seconds: number;
  privacy_mode: boolean;
  privacy_strictness: "standard" | "strict" | "maximum";
  ocr_provider: string;
  ocr_profile: string;
  model_provider: string;
  app_exclusion_patterns: string[];
  evidence_mode: boolean;
  event_count: number;
};

type ContextEvent = {
  id: string;
  timestamp: string;
  active_app: string;
  active_window_title: string;
  detected_topic: string;
  detected_task: string;
  summary_snippet: string;
  sensitivity_score: number;
  raw_artifact_persisted: boolean;
  event_type: string;
  privacy_action?: string;
  redacted_text_snippet?: string;
  redaction_count?: number;
  ocr_provider?: string;
  ocr_profile?: string;
  ocr_confidence?: number | null;
  ocr_elapsed_ms?: number | null;
};

type Note = {
  id: string;
  session_id: string;
  mode: string;
  title: string;
  markdown: string;
  provider: string;
  created_at: string;
};

type Exclusion = {
  id: string;
  pattern: string;
  pattern_type: string;
  enabled: boolean;
  reason: string;
};

type Diagnostics = {
  provider?: string;
  configured_model_provider?: string;
  configured_ocr_provider?: string;
  configured_ocr_profile?: string;
  active_session_id?: string | null;
  require_gpu?: boolean;
  ocr_require_gpu?: boolean;
  mock_mode?: boolean;
  cpu_fallback?: boolean;
  gpu_status?: string;
  backend_containerized?: boolean;
  active_model?: string;
  storage?: { raw_screenshots_persisted: boolean; tmp_dir: string };
  health?: { ok: boolean; message?: string };
  platform?: string;
  live_labeler?: {
    mode: string;
    provider: string;
    model: string;
    gpu_instances: number;
    notes?: string;
  };
  gpu?: {
    gpu_required: boolean;
    gpu_ready: boolean;
    hardware_ready: boolean;
    provider_ready: boolean;
    gpu_provider: string;
    primary_gpu?: {
      name?: string;
      driver_version?: string;
      memory_total_mb?: number;
      memory_free_mb?: number;
      compute_capability?: string;
    } | null;
    packages?: {
      onnxruntime_cuda_provider_available?: boolean;
      paddle_gpu_available?: boolean;
      probe_skipped?: boolean;
    };
    warnings?: string[];
    errors?: string[];
  };
  ocr?: {
    provider: string;
    available: boolean;
    profile: string;
    require_gpu: boolean;
    device?: string;
    reasons?: string[];
  };
};

type CaptureState = {
  stream?: MediaStream;
  video?: HTMLVideoElement;
  canvas?: HTMLCanvasElement;
  sampleCanvas?: HTMLCanvasElement;
  timer?: number;
  inFlight?: boolean;
  activeFrameAbort?: AbortController;
  captureIntervalMs?: number;
  sourceId?: string;
  sourceName?: string;
  previousVisualSample?: Uint8Array;
  visualSkipStreak?: number;
  visualLowChangeStreak?: number;
  paused?: boolean;
  stopRequested?: boolean;
};

type CapturePhase = "idle" | "requesting" | "starting" | "capturing" | "processing" | "paused" | "stopping" | "error";

type CaptureSource = {
  id: string;
  name: string;
};

type PreparedCapture = Pick<CaptureState, "stream" | "video" | "canvas" | "sourceId" | "sourceName">;

type VisualChange = {
  changed: boolean;
  averageDelta: number;
  changedRatio: number;
  sample?: Uint8Array;
};

type CaptureStats = {
  framesAttempted: number;
  framesProcessed: number;
  eventsStored: number;
  framesSkipped: number;
  errors: number;
  lastAction: string;
  lastReason: string;
  lastFrameAt: string;
  lastEventAt: string;
  lastOcrMs?: number | null;
  lastOcrProvider: string;
  lastSnippet: string;
};

const noteModes = [
  ["activity_log", "Activity log"],
  ["clean_summary", "Clean summary"],
  ["sop", "Generate SOP"],
  ["runbook", "Generate runbook"],
  ["ticket_update", "Ticket update"],
  ["decision_record", "Decision record"],
  ["audit_evidence", "Audit evidence"],
  ["recap", "What did I just do?"]
];

const navItems: Array<{ id: View; label: string; icon: LucideIcon }> = [
  { id: "dashboard", label: "Dashboard", icon: Activity },
  { id: "session", label: "Current Session", icon: Gauge },
  { id: "notes", label: "Notes", icon: FileText },
  { id: "history", label: "History", icon: History },
  { id: "runtime", label: "Runtime", icon: Cpu },
  { id: "privacy", label: "Privacy", icon: ShieldCheck },
  { id: "exports", label: "Export Center", icon: Download },
  { id: "diagnostics", label: "Diagnostics", icon: Server }
];

const initialCaptureStats: CaptureStats = {
  framesAttempted: 0,
  framesProcessed: 0,
  eventsStored: 0,
  framesSkipped: 0,
  errors: 0,
  lastAction: "Waiting to start",
  lastReason: "",
  lastFrameAt: "",
  lastEventAt: "",
  lastOcrMs: null,
  lastOcrProvider: "",
  lastSnippet: ""
};

const browserCaptureSource: CaptureSource = {
  id: "browser-picker",
  name: "Browser/system picker"
};

const fastCaptureIntervalSeconds = 0.5;
const visualSampleWidth = 96;
const visualSampleHeight = 54;
const visualDeltaThreshold = 6;
const visualChangedRatioThreshold = 0.0006;
const visualAverageDeltaThreshold = 0.1;
const visualLowChangeRatioThreshold = 0.0001;
const visualLowChangeProbeFrames = 2;
const visualIdleProbeFrames = 20;
const framePostTimeoutMs = 20000;

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...((options?.headers as Record<string, string> | undefined) ?? {})
    }
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}

export default function App() {
  const [view, setView] = useState<View>("dashboard");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSession, setCurrentSession] = useState<Session | null>(null);
  const [events, setEvents] = useState<ContextEvent[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  const [diagnostics, setDiagnostics] = useState<Diagnostics>({});
  const [exclusions, setExclusions] = useState<Exclusion[]>([]);
  const [objective, setObjective] = useState("Keep track of what I work on, how I split my time, and the useful details needed for a clean summary.");
  const [captureInterval, setCaptureInterval] = useState(fastCaptureIntervalSeconds);
  const [privacyMode, setPrivacyMode] = useState(true);
  const [privacyStrictness, setPrivacyStrictness] = useState<"standard" | "strict" | "maximum">("strict");
  const [ocrProvider, setOcrProvider] = useState("paddle");
  const [ocrProfile, setOcrProfile] = useState("screen-fast");
  const [modelProvider, setModelProvider] = useState("onnx-phi");
  const [sessionExclusionText, setSessionExclusionText] = useState("password manager, authenticator, banking");
  const [manualObservation, setManualObservation] = useState("");
  const [statusMessage, setStatusMessage] = useState("Backend check pending");
  const [captureActive, setCaptureActive] = useState(false);
  const [localCaptureConnected, setLocalCaptureConnected] = useState(false);
  const [capturePhase, setCapturePhase] = useState<CapturePhase>("idle");
  const [captureControlBusy, setCaptureControlBusy] = useState<"pause" | "resume" | "stop" | null>(null);
  const [captureStats, setCaptureStats] = useState<CaptureStats>(initialCaptureStats);
  const [noteBusy, setNoteBusy] = useState<string | null>(null);
  const [clockTick, setClockTick] = useState(0);
  const [captureSources, setCaptureSources] = useState<CaptureSource[]>([browserCaptureSource]);
  const [selectedCaptureSourceId, setSelectedCaptureSourceId] = useState(browserCaptureSource.id);
  const captureRef = useRef<CaptureState>({});
  const captureControlIntentRef = useRef(0);
  const runtimeDefaultsAppliedRef = useRef(false);
  const manualObservationRef = useRef("");
  const ocrProviderRef = useRef(ocrProvider);
  const ocrProfileRef = useRef(ocrProfile);

  const activeNote = notes[0];
  const redactionWarnings = events.filter((event) => event.sensitivity_score >= 0.5).length;
  const selectedCaptureSource = captureSources.find((source) => source.id === selectedCaptureSourceId) ?? captureSources[0] ?? browserCaptureSource;
  const captureSupportIssue = captureReadinessIssue(selectedCaptureSource, captureSources);
  const startBusy = ["requesting", "starting", "stopping"].includes(capturePhase);
  const hasOpenSession = Boolean(currentSession && currentSession.status !== "stopped");
  const detachedOpenSession = hasOpenSession && !localCaptureConnected && !captureActive && !startBusy;
  const canStartSession = !captureActive && !startBusy && !captureControlBusy && !captureSupportIssue && (!hasOpenSession || detachedOpenSession);
  const canPauseSession = Boolean(currentSession?.status === "active") && capturePhase !== "stopping" && !captureControlBusy;
  const canResumeSession = Boolean(currentSession?.status === "paused") && !captureActive && !startBusy && !captureControlBusy;
  const canStopSession = hasOpenSession && captureControlBusy !== "stop";

  const refresh = useCallback(async () => {
    try {
      const [sessionList, runtime] = await Promise.all([
        api<Session[]>("/sessions"),
        api<Diagnostics>("/diagnostics")
      ]);
      setSessions(sessionList);
      setDiagnostics(runtime);
      if (!runtimeDefaultsAppliedRef.current) {
        setModelProvider(uiModelProvider(runtime.configured_model_provider ?? runtime.provider ?? "mock"));
        setOcrProvider(uiOcrProvider(runtime.configured_ocr_provider ?? runtime.ocr?.provider ?? "mock"));
        setOcrProfile(runtime.configured_ocr_profile ?? runtime.ocr?.profile ?? "screen-fast");
        runtimeDefaultsAppliedRef.current = true;
      }
      setCurrentSession((previous) => {
        const previousSession = previous ? sessionList.find((session) => session.id === previous.id) ?? null : null;
        if (previousSession) {
          return previousSession;
        }
        if (runtime.active_session_id) {
          return sessionList.find((session) => session.id === runtime.active_session_id) ?? null;
        }
        return null;
      });
      setStatusMessage("Backend healthy");
    } catch (error) {
      setStatusMessage(`Backend unavailable: ${error instanceof Error ? error.message : String(error)}`);
    }
  }, []);

  const refreshCaptureSources = useCallback(async () => {
    const getCaptureSources = window.watcher?.getCaptureSources;
    if (!getCaptureSources) {
      setCaptureSources([browserCaptureSource]);
      setSelectedCaptureSourceId(browserCaptureSource.id);
      return;
    }
    try {
      const sources = (await getCaptureSources())
        .filter((source) => source.id && source.name)
        .map((source) => ({ id: source.id, name: source.name.trim() || source.id }));
      const nextSources = sources.length > 0 ? sources : [browserCaptureSource];
      const preferredSource = sources.find((source) => source.id.startsWith("screen:")) ?? sources[0] ?? browserCaptureSource;
      setCaptureSources(nextSources);
      setSelectedCaptureSourceId((current) => nextSources.some((source) => source.id === current) ? current : preferredSource.id);
    } catch (error) {
      setCaptureSources([browserCaptureSource]);
      setSelectedCaptureSourceId(browserCaptureSource.id);
      setStatusMessage(`Capture sources unavailable: ${error instanceof Error ? error.message : String(error)}`);
    }
  }, []);

  const refreshAll = useCallback(async () => {
    await Promise.allSettled([refresh(), refreshCaptureSources()]);
  }, [refresh, refreshCaptureSources]);

  const refreshSessionDetails = useCallback(async (sessionId: string) => {
    const [eventList, noteList] = await Promise.all([
      api<ContextEvent[]>(`/sessions/${sessionId}/events`),
      api<Note[]>(`/sessions/${sessionId}/notes`)
    ]);
    setEvents(eventList);
    setNotes(noteList);
  }, []);

  useEffect(() => {
    void refreshAll();
    const handle = window.setInterval(() => void refresh(), 7000);
    return () => window.clearInterval(handle);
  }, [refresh, refreshAll]);

  useEffect(() => {
    const handleFocus = () => {
      if (!document.hidden) {
        void refreshAll();
      }
    };
    window.addEventListener("focus", handleFocus);
    document.addEventListener("visibilitychange", handleFocus);
    return () => {
      window.removeEventListener("focus", handleFocus);
      document.removeEventListener("visibilitychange", handleFocus);
    };
  }, [refreshAll]);

  useEffect(() => {
    const handle = window.setInterval(() => setClockTick((value) => (value + 1) % 1000000), 1000);
    return () => window.clearInterval(handle);
  }, []);

  useEffect(() => {
    if (!currentSession) {
      return;
    }
    refreshSessionDetails(currentSession.id).catch((error) => setStatusMessage(String(error)));
    if (currentSession.status === "stopped") {
      return;
    }
    const handle = window.setInterval(() => {
      refreshSessionDetails(currentSession.id).catch((error) => setStatusMessage(String(error)));
    }, 3000);
    return () => window.clearInterval(handle);
  }, [currentSession?.id, currentSession?.status, refreshSessionDetails]);

  useEffect(() => {
    if (!currentSession) {
      return;
    }
    setObjective(currentSession.objective ?? "");
    setCaptureInterval(clampInterval(currentSession.capture_interval_seconds));
    setPrivacyMode(currentSession.privacy_mode);
    setPrivacyStrictness(currentSession.privacy_strictness);
    setOcrProvider(uiOcrProvider(currentSession.ocr_provider));
    setOcrProfile(currentSession.ocr_profile || "screen-fast");
    setModelProvider(uiModelProvider(currentSession.model_provider));
    setSessionExclusionText(currentSession.app_exclusion_patterns.join(", "));
  }, [currentSession?.id]);

  useEffect(() => {
    api<Exclusion[]>("/privacy/exclusions").then(setExclusions).catch(() => undefined);
  }, []);

  useEffect(() => {
    manualObservationRef.current = manualObservation;
  }, [manualObservation]);

  useEffect(() => {
    ocrProviderRef.current = ocrProvider;
    ocrProfileRef.current = ocrProfile;
  }, [ocrProvider, ocrProfile]);

  const startSession = async () => {
    if (captureActive || startBusy || captureControlBusy || (hasOpenSession && !detachedOpenSession)) {
      return;
    }
    if (ocrProvider === "mock" || modelProvider === "mock") {
      setCapturePhase("error");
      setStatusMessage("Live OCR and a live local model are required. Restart with .\\start.ps1 and choose the recommended POC options.");
      return;
    }
    if (captureSupportIssue) {
      setCapturePhase("error");
      setCaptureStats((stats) => ({ ...stats, errors: stats.errors + 1, lastAction: "Capture unavailable", lastReason: captureSupportIssue }));
      setStatusMessage(`Capture unavailable: ${captureSupportIssue}`);
      return;
    }
    const selectedSource = selectedCaptureSource;
    setCaptureStats({
      ...initialCaptureStats,
      lastAction: detachedOpenSession ? "Replacing disconnected session" : (selectedSource.id === browserCaptureSource.id ? "Requesting screen permission" : `Opening ${selectedSource.name}`),
      lastReason: detachedOpenSession ? "backend session was open without a local capture stream" : ""
    });
    setCapturePhase("requesting");
    setStatusMessage(selectedSource.id === browserCaptureSource.id ? "Requesting screen capture permission..." : `Opening capture source: ${selectedSource.name}...`);
    let prepared: PreparedCapture | null = null;
    try {
      prepared = await prepareCaptureStream();
      setCapturePhase("starting");
      setStatusMessage("Creating live session...");
      const session = await api<Session>("/sessions", {
        method: "POST",
        body: JSON.stringify({
          objective,
          capture_interval_seconds: captureInterval,
          privacy_mode: privacyMode,
          privacy_strictness: privacyStrictness,
          ocr_provider: ocrProvider,
          ocr_profile: ocrProfile,
          model_provider: modelProvider,
          app_exclusion_patterns: splitExclusions(sessionExclusionText),
          evidence_mode: false
        })
      });
      setCurrentSession(session);
      setSessions((items) => [session, ...items]);
      setEvents([]);
      setNotes([]);
      setView("session");
      startCaptureLoop(session, prepared);
    } catch (error) {
      prepared?.stream?.getTracks().forEach((track) => track.stop());
      setCaptureActive(false);
      setLocalCaptureConnected(false);
      setCapturePhase("error");
      const message = friendlyCaptureError(error, captureSources);
      setCaptureStats((stats) => ({ ...stats, errors: stats.errors + 1, lastAction: "Capture did not start", lastReason: message }));
      setStatusMessage(`Capture did not start: ${message}`);
    }
  };

  const prepareCaptureStream = async (): Promise<PreparedCapture> => {
    const source = captureSources.find((item) => item.id === selectedCaptureSourceId) ?? browserCaptureSource;
    if (source.id !== browserCaptureSource.id && window.watcher?.setCaptureSource && navigator.mediaDevices?.getDisplayMedia) {
      await window.watcher.setCaptureSource(source.id);
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: {
          frameRate: { ideal: 2, max: 5 },
          width: { ideal: 1280 },
          height: { ideal: 720 }
        },
        audio: false
      });
      return prepareMediaElements(stream, source.id, source.name);
    }
    if (source.id !== browserCaptureSource.id && navigator.mediaDevices?.getUserMedia) {
      const constraints = {
        audio: false,
        video: {
          mandatory: {
            chromeMediaSource: "desktop",
            chromeMediaSourceId: source.id,
            minWidth: 1280,
            maxWidth: 1920,
            minHeight: 720,
            maxHeight: 1080,
            maxFrameRate: 1
          }
        }
      } as unknown as MediaStreamConstraints;
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      return prepareMediaElements(stream, source.id, source.name);
    }
    if (!navigator.mediaDevices?.getDisplayMedia) {
      throw new Error("Screen capture is unavailable in this environment.");
    }
    const stream = await navigator.mediaDevices.getDisplayMedia({
      video: {
        frameRate: { ideal: 2, max: 5 },
        width: { ideal: 1280 },
        height: { ideal: 720 }
      },
      audio: false
    });
    return prepareMediaElements(stream, browserCaptureSource.id, "Browser/system picker");
  };

  const prepareMediaElements = async (stream: MediaStream, sourceId: string, sourceName: string): Promise<PreparedCapture> => {
    const video = document.createElement("video");
    video.srcObject = stream;
    video.muted = true;
    await video.play();
    const canvas = document.createElement("canvas");
    canvas.width = 1280;
    canvas.height = 720;
    return { stream, video, canvas, sourceId, sourceName };
  };

  const startCaptureLoop = (session: Session, prepared: PreparedCapture) => {
    captureRef.current = {
      ...prepared,
      captureIntervalMs: session.capture_interval_seconds * 1000,
      paused: false,
      stopRequested: false
    };
    prepared.stream?.getTracks().forEach((track) => {
      track.onended = () => {
        if (captureRef.current.stream !== prepared.stream || captureRef.current.stopRequested) {
          return;
        }
        if (captureRef.current.timer) {
          window.clearTimeout(captureRef.current.timer);
        }
        captureRef.current.stopRequested = true;
        setCaptureActive(false);
        setLocalCaptureConnected(false);
        setCapturePhase("error");
        setCaptureStats((stats) => ({
          ...stats,
          lastAction: "Screen capture disconnected",
          lastReason: "The selected screen or window stopped sharing. Resume to reconnect, Stop to close the session, or Start New to replace it."
        }));
        setStatusMessage("Screen capture disconnected. Resume to reconnect, Stop to close the session, or Start New to replace it.");
      };
    });
    setCaptureActive(true);
    setLocalCaptureConnected(true);
    setCapturePhase("capturing");
    setCaptureStats((stats) => ({ ...stats, lastAction: `Capture active: ${prepared.sourceName}`, lastReason: "" }));
    setStatusMessage(`Capture active on ${prepared.sourceName}. Processing first frame...`);
    scheduleNextCapture(session.id, 0);
  };

  const scheduleNextCapture = (sessionId: string, delayMs?: number) => {
    const state = captureRef.current;
    if (!state.stream || state.paused || state.stopRequested) {
      return;
    }
    if (state.timer) {
      window.clearTimeout(state.timer);
    }
    state.timer = window.setTimeout(() => void postFrame(sessionId), delayMs ?? state.captureIntervalMs ?? fastCaptureIntervalSeconds * 1000);
  };

  const postFrame = async (sessionId: string) => {
    const state = captureRef.current;
    if (state.inFlight) {
      setCaptureStats((stats) => ({
        ...stats,
        framesAttempted: stats.framesAttempted + 1,
        framesSkipped: stats.framesSkipped + 1,
        lastAction: "Frame skipped",
        lastReason: "ocr_busy"
      }));
      return;
    }
    if (!state.video || !state.canvas) {
      return;
    }
    if (state.paused || state.stopRequested) {
      return;
    }
    state.inFlight = true;
    setCapturePhase("processing");
    setCaptureStats((stats) => ({
      ...stats,
      framesAttempted: stats.framesAttempted + 1,
      lastAction: "Processing frame with OCR/privacy checks",
      lastFrameAt: new Date().toLocaleTimeString(),
      lastReason: ""
    }));
    const context = state.canvas.getContext("2d", { alpha: false });
    if (!context) {
      state.inFlight = false;
      setCapturePhase("error");
      setCaptureStats((stats) => ({ ...stats, errors: stats.errors + 1, lastAction: "Canvas unavailable", lastReason: "Could not create a 2D canvas context." }));
      return;
    }
    let frameRequestTimedOut = false;
    let frameTimeout: number | undefined;
    try {
      context.drawImage(state.video, 0, 0, state.canvas.width, state.canvas.height);
      const trackLabel = state.sourceName || state.stream?.getVideoTracks()[0]?.label || "Desktop capture";
      const text = manualObservationRef.current.trim();
      const visualChange = detectVisualChange(state);
      const captureDecision = shouldCaptureVisualFrame(state, visualChange);
      if (!text && !captureDecision.capture) {
        const visualDetail = `${captureDecision.reason} ${formatChangedRatio(visualChange.changedRatio)} pixels changed`;
        setCaptureStats((stats) => ({
          ...stats,
          framesProcessed: stats.framesProcessed + 1,
          framesSkipped: stats.framesSkipped + 1,
          lastAction: "Frame skipped before OCR",
          lastReason: visualDetail
        }));
        setStatusMessage(`Frame skipped before OCR: ${visualDetail}`);
        return;
      }
      const screenshotBase64 = state.canvas.toDataURL("image/png");
      const frameAbort = new AbortController();
      state.activeFrameAbort = frameAbort;
      frameTimeout = window.setTimeout(() => {
        frameRequestTimedOut = true;
        frameAbort.abort();
      }, framePostTimeoutMs);
      const result = await api<{ skipped: boolean; event?: ContextEvent; reason?: string }>(`/sessions/${sessionId}/events`, {
        method: "POST",
        signal: frameAbort.signal,
        body: JSON.stringify({
          active_app: "Desktop",
          active_window_title: trackLabel,
          capture_source: state.sourceId && state.sourceId !== browserCaptureSource.id ? "electron-desktopCapturer" : "browser-getDisplayMedia",
          screenshot_base64: screenshotBase64,
          ocr_text: text,
          ocr_provider: ocrProviderRef.current,
          ocr_profile: ocrProfileRef.current,
          user_selected_mode: "standard"
        })
      });
      if (state.stopRequested) {
        return;
      }
      if (result.event) {
        setEvents((items) => [...items, result.event as ContextEvent]);
        setCaptureStats((stats) => ({
          ...stats,
          framesProcessed: stats.framesProcessed + 1,
          eventsStored: stats.eventsStored + 1,
          lastAction: "Stored redacted context event",
          lastReason: result.event?.privacy_action ?? "store_redacted",
          lastEventAt: new Date().toLocaleTimeString(),
          lastOcrMs: result.event?.ocr_elapsed_ms,
          lastOcrProvider: result.event?.ocr_provider ?? "",
          lastSnippet: result.event?.summary_snippet || result.event?.redacted_text_snippet || "Metadata/hash event stored"
        }));
        if (text) {
          manualObservationRef.current = "";
          setManualObservation("");
        }
        setStatusMessage("Frame processed, raw screenshot discarded");
      } else if (result.skipped) {
        setCaptureStats((stats) => ({
          ...stats,
          framesProcessed: stats.framesProcessed + 1,
          framesSkipped: stats.framesSkipped + 1,
          lastAction: "Frame skipped",
          lastReason: result.reason ?? "unknown"
        }));
        setStatusMessage(`Frame skipped: ${result.reason}`);
      }
    } catch (error) {
      if (state.stopRequested && isAbortError(error)) {
        return;
      }
      const message = frameRequestTimedOut && isAbortError(error)
        ? `Frame processing timed out after ${Math.round(framePostTimeoutMs / 1000)}s. The capture loop will continue.`
        : (error instanceof Error ? error.message : String(error));
      setCaptureStats((stats) => ({ ...stats, errors: stats.errors + 1, lastAction: "Frame processing failed", lastReason: message }));
      setStatusMessage(`Frame processing failed: ${message}`);
    } finally {
      if (frameTimeout) {
        window.clearTimeout(frameTimeout);
      }
      state.activeFrameAbort = undefined;
      state.inFlight = false;
      if (state.stopRequested) {
        setCapturePhase(captureRef.current.stream ? "stopping" : "idle");
      } else if (state.paused) {
        setCapturePhase("paused");
      } else {
        setCapturePhase(captureRef.current.stream ? "capturing" : "idle");
        scheduleNextCapture(sessionId);
      }
    }
  };

  const pauseCapture = async () => {
    if (!currentSession || captureControlBusy) return;
    const intent = captureControlIntentRef.current + 1;
    captureControlIntentRef.current = intent;
    setCaptureControlBusy("pause");
    const state = captureRef.current;
    state.paused = true;
    if (state.timer) {
      window.clearTimeout(state.timer);
      state.timer = undefined;
    }
    setCapturePhase("paused");
    setCaptureActive(false);
    setCaptureStats((stats) => ({
      ...stats,
      lastAction: "Pause requested",
      lastReason: state.inFlight ? "finishing current OCR request" : ""
    }));
    setStatusMessage(state.inFlight ? "Pause requested. Finishing the current OCR request..." : "Pausing capture...");
    try {
      const session = await api<Session>(`/sessions/${currentSession.id}/pause`, { method: "POST" });
      if (captureControlIntentRef.current !== intent || state.stopRequested) {
        return;
      }
      setCurrentSession(session);
      setCaptureStats((stats) => ({ ...stats, lastAction: "Capture paused", lastReason: "" }));
      setStatusMessage("Capture paused.");
      await refresh();
    } catch (error) {
      if (captureControlIntentRef.current !== intent || state.stopRequested) {
        return;
      }
      state.paused = false;
      setCaptureActive(Boolean(state.stream));
      setCapturePhase(state.stream ? "capturing" : "error");
      const message = error instanceof Error ? error.message : String(error);
      setCaptureStats((stats) => ({ ...stats, errors: stats.errors + 1, lastAction: "Pause failed", lastReason: message }));
      setStatusMessage(`Pause failed: ${message}`);
    } finally {
      if (captureControlIntentRef.current === intent) {
        setCaptureControlBusy(null);
      }
    }
  };

  const resumeCapture = async () => {
    if (!currentSession || captureControlBusy) return;
    const intent = captureControlIntentRef.current + 1;
    captureControlIntentRef.current = intent;
    setCaptureControlBusy("resume");
    setStatusMessage("Resuming capture...");
    try {
      const session = await api<Session>(`/sessions/${currentSession.id}/resume`, { method: "POST" });
      if (captureControlIntentRef.current !== intent || captureRef.current.stopRequested) {
        return;
      }
      setCurrentSession(session);
      if (captureRef.current.video && captureRef.current.canvas && captureRef.current.stream) {
        captureRef.current.paused = false;
        captureRef.current.stopRequested = false;
        captureRef.current.captureIntervalMs = session.capture_interval_seconds * 1000;
        if (captureRef.current.timer) {
          window.clearTimeout(captureRef.current.timer);
        }
        setCaptureActive(true);
        setLocalCaptureConnected(true);
        setCapturePhase("capturing");
        setCaptureStats((stats) => ({ ...stats, lastAction: "Capture resumed", lastReason: "" }));
        setStatusMessage("Capture resumed. Processing frames...");
        scheduleNextCapture(session.id, 0);
      } else {
        setCapturePhase("requesting");
        const prepared = await prepareCaptureStream();
        startCaptureLoop(session, prepared);
      }
      await refresh();
    } catch (error) {
      if (captureControlIntentRef.current !== intent || captureRef.current.stopRequested) {
        return;
      }
      const message = error instanceof Error ? error.message : String(error);
      setCapturePhase("error");
      setCaptureStats((stats) => ({ ...stats, errors: stats.errors + 1, lastAction: "Resume failed", lastReason: message }));
      setStatusMessage(`Resume failed: ${message}`);
    } finally {
      if (captureControlIntentRef.current === intent) {
        setCaptureControlBusy(null);
      }
    }
  };

  const generateActivityLogAfterStop = async (sessionId: string) => {
    setNoteBusy("activity_log");
    try {
      const note = await api<Note>(`/sessions/${sessionId}/notes`, {
        method: "POST",
        body: JSON.stringify({ mode: "activity_log" })
      });
      setNotes((items) => [note, ...items]);
      setView("notes");
      setStatusMessage(`Capture stopped. Generated ${note.title}.`);
    } catch (error) {
      setStatusMessage(`Capture stopped, but note generation failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setNoteBusy(null);
    }
  };

  const stopCapture = async () => {
    if (!currentSession || captureControlBusy === "stop") return;
    const intent = captureControlIntentRef.current + 1;
    captureControlIntentRef.current = intent;
    setCaptureControlBusy("stop");
    const sessionToStop = currentSession;
    const stoppingState = captureRef.current;
    const hadInFlightFrame = Boolean(stoppingState.inFlight);
    stoppingState.stopRequested = true;
    setCapturePhase("stopping");
    setCaptureActive(false);
    setCaptureStats((stats) => ({
      ...stats,
      lastAction: "Stop requested",
      lastReason: hadInFlightFrame ? "finishing current OCR request" : ""
    }));
    setStatusMessage(hadInFlightFrame ? "Stop requested. Finishing the current OCR request and cleaning up..." : "Stopping capture and cleaning temporary files...");
    stopLocalStream();
    try {
      const stoppedSession = await api<Session>(`/sessions/${sessionToStop.id}/stop`, { method: "POST" });
      if (captureControlIntentRef.current !== intent) {
        return;
      }
      setCurrentSession(stoppedSession);
      setCapturePhase("idle");
      const eventList = await api<ContextEvent[]>(`/sessions/${sessionToStop.id}/events`);
      setEvents(eventList);
      if (eventList.length > 0) {
        setStatusMessage("Capture stopped. Generating activity log in the background...");
        void generateActivityLogAfterStop(sessionToStop.id);
      } else {
        setStatusMessage(`Capture stopped. No events were stored. Last status: ${captureStats.lastAction}${captureStats.lastReason ? ` (${captureStats.lastReason})` : ""}.`);
      }
      await refresh();
    } catch (error) {
      setCapturePhase("error");
      const message = error instanceof Error ? error.message : String(error);
      setCaptureStats((stats) => ({ ...stats, errors: stats.errors + 1, lastAction: "Stop failed", lastReason: message }));
      setStatusMessage(`Stop failed locally after the stream was halted: ${message}`);
    } finally {
      if (captureControlIntentRef.current === intent) {
        setCaptureControlBusy(null);
      }
    }
  };

  const stopLocalStream = () => {
    const state = captureRef.current;
    state.stopRequested = true;
    state.activeFrameAbort?.abort();
    if (state.timer) {
      window.clearTimeout(state.timer);
    }
    state.stream?.getTracks().forEach((track) => track.stop());
    captureRef.current = { stopRequested: true };
    setLocalCaptureConnected(false);
  };

  const generateNote = async (mode: string) => {
    if (!currentSession || noteBusy) return;
    setNoteBusy(mode);
    setStatusMessage(`Generating ${noteModeLabel(mode)}...`);
    try {
      const note = await api<Note>(`/sessions/${currentSession.id}/notes`, {
        method: "POST",
        body: JSON.stringify({ mode })
      });
      setNotes((items) => [note, ...items]);
      setView("notes");
      setStatusMessage(`Generated ${note.title}.`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStatusMessage(`Note generation failed: ${message}`);
    } finally {
      setNoteBusy(null);
    }
  };

  const exportNote = async (noteId: string) => {
    const result = await api<{ exported: boolean; path: string }>(`/notes/${noteId}/export`, { method: "POST" });
    setStatusMessage(`Markdown exported to ${result.path}`);
  };

  const deleteSession = async (sessionId: string) => {
    if (!window.confirm("Delete this session, generated notes, exports, and temporary processing files?")) {
      return;
    }
    if (currentSession?.id === sessionId) {
      stopLocalStream();
      setCaptureActive(false);
      setCurrentSession(null);
      setEvents([]);
      setNotes([]);
    }
    const result = await api<{ tmp_files_removed: number; exports_removed: number; raw_artifacts_deleted: number }>(`/sessions/${sessionId}`, { method: "DELETE" });
    setStatusMessage(`Session deleted. Temp files removed: ${result.tmp_files_removed}; exports removed: ${result.exports_removed}; raw artifacts deleted: ${result.raw_artifacts_deleted}.`);
    await refresh();
  };

  const resetLocalData = async () => {
    if (!window.confirm("Delete all sessions, notes, exports, and temporary processing files? Raw screenshots are not stored, but this clears the local POC memory database.")) {
      return;
    }
    stopLocalStream();
    setCaptureActive(false);
    setCapturePhase("idle");
    const result = await api<{ deleted: boolean; counts_before_delete: Record<string, number>; tmp_files_removed: number; exports_removed: number }>("/data", { method: "DELETE" });
    setCurrentSession(null);
    setSessions([]);
    setEvents([]);
    setNotes([]);
    setCaptureStats(initialCaptureStats);
    setStatusMessage(`Local POC data reset. Removed ${result.counts_before_delete.sessions ?? 0} sessions, ${result.counts_before_delete.events ?? 0} events, ${result.exports_removed} exports, and ${result.tmp_files_removed} temp files.`);
    await refresh();
  };

  const addDefaultExclusion = async () => {
    const rule = await api<Exclusion>("/privacy/exclusions", {
      method: "POST",
      body: JSON.stringify({
        pattern: "password",
        pattern_type: "both",
        reason: "Default sensitive window guard"
      })
    });
    setExclusions((items) => [rule, ...items]);
  };

  const sessionDuration = useMemo(() => {
    if (!currentSession?.started_at) return "No active session";
    const start = new Date(currentSession.started_at).getTime();
    const end = currentSession.ended_at ? new Date(currentSession.ended_at).getTime() : Date.now();
    const total = Math.max(0, Math.floor((end - start) / 1000));
    const minutes = Math.floor(total / 60).toString().padStart(2, "0");
    const seconds = (total % 60).toString().padStart(2, "0");
    return `${minutes}:${seconds}`;
  }, [currentSession, clockTick]);

  const captureBannerHeadline = detachedOpenSession
    ? "Session open, capture stream disconnected"
    : (captureSupportIssue && !captureActive ? "Desktop capture required" : captureHeadline(capturePhase, captureActive));
  const captureBannerDetail = detachedOpenSession
    ? "The backend has an open session, but this window is not capturing. Resume to reconnect, Stop to close it, or Start New to replace it."
    : (captureSupportIssue && !captureActive ? captureSupportIssue : captureDetail(capturePhase, captureStats));
  const capturePillTone = detachedOpenSession ? "warning" : (captureActive ? "live" : "idle");
  const capturePillLabel = detachedOpenSession ? "Capture disconnected" : (captureActive ? "Capture active" : "Capture idle");

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><ScrollText size={20} /></div>
          <div>
            <strong>Watcher</strong>
            <span>Private documentation assistant</span>
          </div>
        </div>
        <nav>
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.id} className={view === item.id ? "nav-item active" : "nav-item"} onClick={() => setView(item.id)}>
                <Icon size={18} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <StatusPill tone={capturePillTone} icon={<Activity size={14} />} label={capturePillLabel} />
          <StatusPill tone={diagnostics.mock_mode ? "warning" : "ok"} icon={<Cpu size={14} />} label={diagnostics.mock_mode ? "Live AI unavailable" : "Live local AI"} />
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <h1>{titleForView(view)}</h1>
            <p>{statusMessage}</p>
          </div>
          <div className="top-status">
            <StatusPill tone={diagnostics.cpu_fallback ? "warning" : "ok"} icon={<Cpu size={14} />} label={diagnostics.cpu_fallback ? "CPU fallback active" : "GPU status checked"} />
            <StatusPill tone="ok" icon={<Database size={14} />} label="No raw screenshots stored" />
            <button className="icon-button" onClick={() => void refreshAll()} title="Refresh status and capture sources"><RefreshCw size={17} /></button>
          </div>
        </header>

        <div className="capture-bar">
          <div>
            <strong>{captureBannerHeadline}</strong>
            <span>{captureBannerDetail}</span>
          </div>
          <div className="capture-actions">
            <button className="primary" onClick={startSession} title={canStartSession ? (detachedOpenSession ? "Start a fresh session and close the disconnected backend session." : "Start capture") : captureSupportIssue || (hasOpenSession ? "Pause, resume, or stop the current session first." : "Start capture")} disabled={!canStartSession}><Play size={16} /> {detachedOpenSession ? "Start New" : "Start"}</button>
            <button onClick={pauseCapture} disabled={!canPauseSession}><Pause size={16} /> Pause</button>
            <button onClick={resumeCapture} disabled={!canResumeSession}><Play size={16} /> Resume</button>
            <button className="danger" onClick={stopCapture} disabled={!canStopSession}><Square size={16} /> Stop</button>
          </div>
        </div>

        <section className="content-grid">
          <div className="primary-pane">
            {view === "dashboard" && (
              <Dashboard
                objective={objective}
                setObjective={setObjective}
                captureInterval={captureInterval}
                setCaptureInterval={setCaptureInterval}
                privacyMode={privacyMode}
                setPrivacyMode={setPrivacyMode}
                privacyStrictness={privacyStrictness}
                setPrivacyStrictness={setPrivacyStrictness}
                ocrProvider={ocrProvider}
                setOcrProvider={setOcrProvider}
                ocrProfile={ocrProfile}
                setOcrProfile={setOcrProfile}
                modelProvider={modelProvider}
                setModelProvider={setModelProvider}
                captureSources={captureSources}
                selectedCaptureSourceId={selectedCaptureSourceId}
                setSelectedCaptureSourceId={setSelectedCaptureSourceId}
                captureSupportIssue={captureSupportIssue}
                detachedOpenSession={detachedOpenSession}
                sessionExclusionText={sessionExclusionText}
                setSessionExclusionText={setSessionExclusionText}
                currentSession={currentSession}
                capturePhase={capturePhase}
                sessionDuration={sessionDuration}
                events={events}
                notes={notes}
                noteBusy={noteBusy}
                onGenerate={generateNote}
              />
            )}
            {view === "session" && (
              <CurrentSession
                currentSession={currentSession}
                objective={objective}
                events={events}
                capturePhase={capturePhase}
                localCaptureConnected={localCaptureConnected}
                detachedOpenSession={detachedOpenSession}
                captureStats={captureStats}
                manualObservation={manualObservation}
                setManualObservation={setManualObservation}
                noteBusy={noteBusy}
                onGenerate={generateNote}
              />
            )}
            {view === "notes" && <NotesPanel notes={notes} activeNote={activeNote} onExport={exportNote} />}
            {view === "history" && <HistoryPanel sessions={sessions} onDelete={deleteSession} onResetAll={resetLocalData} />}
            {view === "runtime" && <RuntimePanel diagnostics={diagnostics} />}
            {view === "privacy" && <PrivacyPanel exclusions={exclusions} onAdd={addDefaultExclusion} />}
            {view === "exports" && <ExportsPanel activeNote={activeNote} onExport={exportNote} />}
            {view === "diagnostics" && <DiagnosticsPanel diagnostics={diagnostics} />}
          </div>

          <aside className="right-rail">
            <section className="rail-section">
              <h2>Session</h2>
              <Metric label="Duration" value={sessionDuration} />
              <Metric label="Events" value={String(events.length)} />
              <Metric label="Redaction warnings" value={String(redactionWarnings)} />
            </section>
            <section className="rail-section">
              <h2>Runtime</h2>
              <StatusLine label="Provider" value={diagnostics.provider ?? "not configured"} />
              <StatusLine label="Model" value={diagnostics.active_model ?? "not selected"} />
              <StatusLine label="GPU" value={diagnostics.gpu_status ?? "unknown"} />
              <StatusLine label="OCR" value={diagnostics.ocr?.provider ?? "not configured"} />
              <StatusLine label="Live labeler" value={diagnostics.live_labeler?.model ?? "not configured"} />
              <StatusLine label="Location" value={diagnostics.backend_containerized ? "containerized backend" : "host backend"} />
            </section>
            <section className="rail-section">
              <h2>Privacy</h2>
              <StatusLine label="Screenshot archive" value="disabled" />
              <StatusLine label="OCR storage" value="redacted or metadata-only" />
              <StatusLine label="Evidence mode" value={currentSession?.evidence_mode ? "enabled" : "disabled"} />
            </section>
          </aside>
        </section>
      </main>
    </div>
  );
}

function Dashboard(props: {
  objective: string;
  setObjective: (value: string) => void;
  captureInterval: number;
  setCaptureInterval: (value: number) => void;
  privacyMode: boolean;
  setPrivacyMode: (value: boolean) => void;
  privacyStrictness: "standard" | "strict" | "maximum";
  setPrivacyStrictness: (value: "standard" | "strict" | "maximum") => void;
  ocrProvider: string;
  setOcrProvider: (value: string) => void;
  ocrProfile: string;
  setOcrProfile: (value: string) => void;
  modelProvider: string;
  setModelProvider: (value: string) => void;
  captureSources: CaptureSource[];
  selectedCaptureSourceId: string;
  setSelectedCaptureSourceId: (value: string) => void;
  captureSupportIssue: string;
  detachedOpenSession: boolean;
  sessionExclusionText: string;
  setSessionExclusionText: (value: string) => void;
  currentSession: Session | null;
  capturePhase: CapturePhase;
  sessionDuration: string;
  events: ContextEvent[];
  notes: Note[];
  noteBusy: string | null;
  onGenerate: (mode: string) => void;
}) {
  return (
    <div className="stack">
      <section className="band">
        <div>
          <h2>Session goal</h2>
          <p>Plain-language instruction for interpreting this capture session.</p>
        </div>
        <textarea
          value={props.objective}
          onChange={(event) => props.setObjective(event.target.value)}
          placeholder="Example: I'm going to work on marketing material and school work. Keep track of how I split my time and what I do for each task."
        />
      </section>
      <section className="settings-surface">
        <label>
          <span>Interval</span>
          <input
            type="number"
            min="0.5"
            max="60"
            step="0.5"
            value={props.captureInterval}
            onChange={(event) => props.setCaptureInterval(clampInterval(Number(event.target.value)))}
          />
        </label>
        <label>
          <span>Privacy</span>
          <select value={props.privacyMode ? "on" : "off"} onChange={(event) => props.setPrivacyMode(event.target.value === "on")}>
            <option value="on">On</option>
            <option value="off">Off</option>
          </select>
        </label>
        <label>
          <span>Strictness</span>
          <select value={props.privacyStrictness} onChange={(event) => props.setPrivacyStrictness(event.target.value as "standard" | "strict" | "maximum")}>
            <option value="standard">Standard</option>
            <option value="strict">Strict</option>
            <option value="maximum">Maximum</option>
          </select>
        </label>
        <label>
          <span>OCR</span>
          <select value={props.ocrProvider} onChange={(event) => props.setOcrProvider(event.target.value)}>
            <option value="paddle">PaddleOCR</option>
          </select>
        </label>
        <label>
          <span>OCR profile</span>
          <select value={props.ocrProfile} onChange={(event) => props.setOcrProfile(event.target.value)}>
            <option value="screen-fast">Screen fast</option>
            <option value="screen-accurate">Screen accurate</option>
          </select>
        </label>
        <label>
          <span>Reasoning LLM</span>
          <select value={props.modelProvider} onChange={(event) => props.setModelProvider(event.target.value)}>
            <option value="onnx-phi">ONNX Phi</option>
            <option value="ollama">Ollama</option>
            <option value="lmstudio">LM Studio</option>
          </select>
        </label>
        <label className="wide-control">
          <span>Capture source</span>
          <select value={props.selectedCaptureSourceId} onChange={(event) => props.setSelectedCaptureSourceId(event.target.value)}>
            {props.captureSources.map((source) => (
              <option key={source.id} value={source.id}>{source.name}</option>
            ))}
          </select>
        </label>
        <label className="wide-control">
          <span>Window exclusions</span>
          <input value={props.sessionExclusionText} onChange={(event) => props.setSessionExclusionText(event.target.value)} />
        </label>
      </section>
      {props.captureSupportIssue && (
        <section className="inline-alert">
          <AlertTriangle size={18} />
          <div>
            <strong>Capture is unavailable in this window</strong>
            <span>{props.captureSupportIssue}</span>
          </div>
        </section>
      )}
      {props.detachedOpenSession && (
        <section className="inline-alert">
          <AlertTriangle size={18} />
          <div>
            <strong>Capture session needs reconnect</strong>
            <span>The backend still has an open session, but this window is not receiving frames. Use Resume, Stop, or Start New from the top bar.</span>
          </div>
        </section>
      )}
      <div className="metrics-row">
        <MetricBlock icon={<Activity />} label="Capture status" value={props.detachedOpenSession ? "Reconnect needed" : (props.captureSupportIssue ? "Desktop app needed" : capturePhaseLabel(props.capturePhase))} />
        <MetricBlock icon={<History />} label="Duration" value={props.sessionDuration} />
        <MetricBlock icon={<Database />} label="Events captured" value={String(props.events.length)} />
        <MetricBlock icon={<FileText />} label="Notes generated" value={String(props.notes.length)} />
      </div>
      <section className="action-strip">
        {noteModes.slice(1, 5).map(([mode, label]) => (
          <button key={mode} onClick={() => props.onGenerate(mode)} disabled={!props.currentSession || Boolean(props.noteBusy)}>
            <FileText size={16} /> {label}
          </button>
        ))}
      </section>
    </div>
  );
}

function CurrentSession(props: {
  currentSession: Session | null;
  objective: string;
  events: ContextEvent[];
  capturePhase: CapturePhase;
  localCaptureConnected: boolean;
  detachedOpenSession: boolean;
  captureStats: CaptureStats;
  manualObservation: string;
  setManualObservation: (value: string) => void;
  noteBusy: string | null;
  onGenerate: (mode: string) => void;
}) {
  return (
    <div className="split-pane">
      <section className="live-preview">
        <h2>Live Context Preview</h2>
        <p className="muted">Recent structured events. Raw frames are not shown or stored after processing.</p>
        <div className="event-list">
          {props.events.slice(-9).reverse().map((event) => (
            <article className="event-row" key={event.id}>
              <div className={event.sensitivity_score >= 0.5 ? "event-dot warning" : "event-dot"} />
              <div>
                <strong>{event.active_app || "Desktop"} / {event.active_window_title || "Unknown window"}</strong>
                <p>{event.summary_snippet || event.redacted_text_snippet || "Frame hash captured; no redacted OCR text available."}</p>
                <div className="event-meta">
                  <span>{event.privacy_action ?? event.event_type}</span>
                  <span>{event.detected_topic}</span>
                  <span>{event.detected_task}</span>
                  <span>{event.redaction_count ?? 0} redactions</span>
                  {event.ocr_confidence != null && <span>{Math.round(event.ocr_confidence * 100)}% OCR</span>}
                  {event.ocr_elapsed_ms != null && <span>{Math.round(event.ocr_elapsed_ms)} ms</span>}
                </div>
              </div>
            </article>
          ))}
          {props.events.length === 0 && <EmptyState text="Start capture to create redacted, structured context events." />}
        </div>
      </section>
      <section className="note-composer">
        <h2>Session Controls</h2>
        <div className="session-settings-summary">
          <StatusLine label="Session goal" value={props.currentSession?.objective || props.objective || "Not provided"} />
          <StatusLine label="Capture state" value={capturePhaseLabel(props.capturePhase)} />
          <StatusLine label="Capture connection" value={props.detachedOpenSession ? "needs reconnect" : (props.localCaptureConnected ? "connected" : "not connected")} />
          <StatusLine label="Frames attempted" value={String(props.captureStats.framesAttempted)} />
          <StatusLine label="Frames processed" value={String(props.captureStats.framesProcessed)} />
          <StatusLine label="Events stored" value={String(props.captureStats.eventsStored)} />
          <StatusLine label="Frames skipped" value={String(props.captureStats.framesSkipped)} />
          <StatusLine label="Errors" value={String(props.captureStats.errors)} />
          <StatusLine label="Last action" value={props.captureStats.lastAction} />
          {props.captureStats.lastReason && <StatusLine label="Last reason" value={props.captureStats.lastReason} />}
          {props.captureStats.lastOcrMs != null && <StatusLine label="Last OCR" value={`${Math.round(props.captureStats.lastOcrMs)} ms ${props.captureStats.lastOcrProvider ? `via ${props.captureStats.lastOcrProvider}` : ""}`} />}
        </div>
        {props.currentSession && (
          <div className="session-settings-summary">
            <StatusLine label="Capture interval" value={`${props.currentSession.capture_interval_seconds}s`} />
            <StatusLine label="Privacy" value={`${props.currentSession.privacy_mode ? "on" : "off"} / ${props.currentSession.privacy_strictness}`} />
            <StatusLine label="OCR" value={`${props.currentSession.ocr_provider} / ${props.currentSession.ocr_profile}`} />
            <StatusLine label="Live labeler" value="fast local labeler" />
            <StatusLine label="Reasoning LLM" value={props.currentSession.model_provider} />
          </div>
        )}
        <textarea
          value={props.manualObservation}
          onChange={(event) => props.setManualObservation(event.target.value)}
          placeholder="Optional manual observation for the next event"
        />
        <div className="mode-grid">
          {noteModes.map(([mode, label]) => (
            <button key={mode} onClick={() => props.onGenerate(mode)} disabled={!props.currentSession || Boolean(props.noteBusy)}>
              <ScrollText size={16} /> {label}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

function NotesPanel(props: { notes: Note[]; activeNote?: Note; onExport: (noteId: string) => void }) {
  return (
    <div className="split-pane">
      <section className="note-list">
        <h2>Generated Notes</h2>
        {props.notes.map((note) => (
          <article className="note-item" key={note.id}>
            <strong>{note.title}</strong>
            <span>{note.mode} - {note.provider}</span>
          </article>
        ))}
        {props.notes.length === 0 && <EmptyState text="Generate a Markdown note from a session to see it here." />}
      </section>
      <section className="markdown-editor">
        <div className="editor-header">
          <h2>{props.activeNote?.title ?? "Notes editor"}</h2>
          <button disabled={!props.activeNote} onClick={() => props.activeNote && props.onExport(props.activeNote.id)}>
            <Download size={16} /> Export Markdown
          </button>
        </div>
        <textarea value={props.activeNote?.markdown ?? ""} readOnly placeholder="Generated Markdown will appear here." />
      </section>
    </div>
  );
}

function HistoryPanel(props: { sessions: Session[]; onDelete: (sessionId: string) => void; onResetAll: () => void }) {
  return (
    <section className="table-surface">
      <div className="table-header">
        <h2>Session History</h2>
        <div className="table-actions">
          <span>{props.sessions.length} sessions</span>
          <button className="danger subtle" onClick={props.onResetAll}><Trash2 size={16} /> Reset POC data</button>
        </div>
      </div>
      {props.sessions.map((session) => (
        <div className="history-row" key={session.id}>
          <div>
            <strong>{session.objective || "Untitled session"}</strong>
            <span>{session.status} - {session.event_count} events - {new Date(session.started_at).toLocaleString()}</span>
          </div>
          <button className="danger subtle" onClick={() => props.onDelete(session.id)}><Trash2 size={16} /> Delete</button>
        </div>
      ))}
    </section>
  );
}

function RuntimePanel({ diagnostics }: { diagnostics: Diagnostics }) {
  const gpu = diagnostics.gpu;
  const gpuLabel = gpu?.primary_gpu?.name ?? (gpu?.hardware_ready ? "Detected" : "Not detected");
  const vramLabel = gpu?.primary_gpu?.memory_total_mb
    ? `${gpu.primary_gpu.memory_free_mb ?? "?"}/${gpu.primary_gpu.memory_total_mb} MB free`
    : "unknown";
  const providerLabel = gpu?.gpu_provider ?? diagnostics.gpu_status ?? "unknown";
  const gateLabel = gpu?.gpu_required ? (gpu.gpu_ready ? "GPU required and present" : "GPU required, not ready") : "Not required";
  const ocrLabel = diagnostics.ocr
    ? `${diagnostics.ocr.provider} / ${diagnostics.ocr.available ? "ready" : "not ready"}`
    : "not configured";
  const labelerLabel = diagnostics.live_labeler
    ? `${diagnostics.live_labeler.provider} / ${diagnostics.live_labeler.model}`
    : "not configured";
  return (
    <div className="stack">
      <section className="band">
        <Cpu size={28} />
        <div>
          <h2>AI / Runtime Status</h2>
          <p>{diagnostics.mock_mode ? "Live local AI is not configured. Start with .\\start.ps1 and choose the recommended POC runtime." : "Local runtime configured."}</p>
        </div>
      </section>
      <div className="metrics-row">
        <MetricBlock icon={<Server />} label="Provider" value={diagnostics.provider ?? "not configured"} />
        <MetricBlock icon={<Cpu />} label="GPU" value={providerLabel} />
        <MetricBlock icon={<Gauge />} label="Fallback" value={diagnostics.cpu_fallback ? "CPU fallback active" : "No fallback"} />
        <MetricBlock icon={<FileText />} label="OCR" value={ocrLabel} />
        <MetricBlock icon={<ScrollText />} label="Live labeler" value={labelerLabel} />
      </div>
      <section className="table-surface compact-status">
        <StatusLine label="GPU gate" value={gateLabel} />
        <StatusLine label="GPU name" value={gpuLabel} />
        <StatusLine label="VRAM" value={vramLabel} />
        <StatusLine label="CUDA provider" value={gpu?.packages?.onnxruntime_cuda_provider_available ? "ready" : "not ready"} />
        <StatusLine label="Paddle GPU" value={gpu?.packages?.paddle_gpu_available ? "ready" : "not ready"} />
        <StatusLine label="OCR profile" value={diagnostics.ocr?.profile ?? "screen-fast"} />
        <StatusLine label="OCR device" value={diagnostics.ocr?.device ?? "none"} />
        <StatusLine label="Live labeler mode" value={diagnostics.live_labeler?.mode ?? "not configured"} />
        <StatusLine label="Live labeler GPU instances" value={String(diagnostics.live_labeler?.gpu_instances ?? 0)} />
      </section>
    </div>
  );
}

function PrivacyPanel({ exclusions, onAdd }: { exclusions: Exclusion[]; onAdd: () => void }) {
  return (
    <div className="stack">
      <section className="band">
        <LockKeyhole size={28} />
        <div>
          <h2>Privacy / Redaction Settings</h2>
          <p>Clipboard capture and keylogging are not implemented. Raw screenshots are discarded after processing.</p>
        </div>
        <button onClick={onAdd}><EyeOff size={16} /> Add password exclusion</button>
      </section>
      <section className="table-surface">
        {exclusions.map((rule) => (
          <div className="history-row" key={rule.id}>
            <div>
              <strong>{rule.pattern}</strong>
              <span>{rule.pattern_type} - {rule.enabled ? "enabled" : "disabled"} - {rule.reason}</span>
            </div>
          </div>
        ))}
        {exclusions.length === 0 && <EmptyState text="No custom exclusions yet. Sensitive window and secret redaction still run by default." />}
      </section>
    </div>
  );
}

function ExportsPanel({ activeNote, onExport }: { activeNote?: Note; onExport: (noteId: string) => void }) {
  return (
    <section className="band">
      <Download size={28} />
      <div>
        <h2>Export Center</h2>
        <p>Export generated Markdown only. Raw screen captures are not exportable in the MVP.</p>
      </div>
      <button disabled={!activeNote} onClick={() => activeNote && onExport(activeNote.id)}>
        <Clipboard size={16} /> Export Markdown
      </button>
    </section>
  );
}

function DiagnosticsPanel({ diagnostics }: { diagnostics: Diagnostics }) {
  return (
    <section className="diagnostics">
      <h2>Diagnostics</h2>
      <pre>{JSON.stringify(diagnostics, null, 2)}</pre>
    </section>
  );
}

function StatusPill({ tone, icon, label }: { tone: "live" | "idle" | "ok" | "warning"; icon: ReactNode; label: string }) {
  return <span className={`status-pill ${tone}`}>{icon}{label}</span>;
}

function StatusLine({ label, value }: { label: string; value: string }) {
  return <div className="status-line"><span>{label}</span><strong>{value}</strong></div>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
}

function MetricBlock({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return <div className="metric-block">{icon}<span>{label}</span><strong>{value}</strong></div>;
}

function EmptyState({ text }: { text: string }) {
  return <div className="empty-state"><AlertTriangle size={18} /> {text}</div>;
}

function titleForView(view: View) {
  const item = navItems.find((nav) => nav.id === view);
  return item?.label ?? "Dashboard";
}

function noteModeLabel(mode: string) {
  return noteModes.find(([value]) => value === mode)?.[1] ?? "note";
}

function isAbortError(error: unknown) {
  return error instanceof Error && error.name === "AbortError";
}

function splitExclusions(value: string) {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function clampInterval(value: number) {
  if (!Number.isFinite(value)) return fastCaptureIntervalSeconds;
  return Math.min(60, Math.max(0.5, value));
}

function detectVisualChange(state: CaptureState): VisualChange {
  if (!state.canvas) {
    return { changed: true, averageDelta: 255, changedRatio: 1 };
  }
  if (!state.sampleCanvas) {
    state.sampleCanvas = document.createElement("canvas");
    state.sampleCanvas.width = visualSampleWidth;
    state.sampleCanvas.height = visualSampleHeight;
  }
  const sampleContext = state.sampleCanvas.getContext("2d", { alpha: false, willReadFrequently: true });
  if (!sampleContext) {
    return { changed: true, averageDelta: 255, changedRatio: 1 };
  }
  sampleContext.drawImage(state.canvas, 0, 0, visualSampleWidth, visualSampleHeight);
  const pixels = sampleContext.getImageData(0, 0, visualSampleWidth, visualSampleHeight).data;
  const sample = new Uint8Array(visualSampleWidth * visualSampleHeight);
  for (let index = 0, pixelIndex = 0; index < pixels.length; index += 4, pixelIndex += 1) {
    sample[pixelIndex] = Math.round((pixels[index] * 0.299) + (pixels[index + 1] * 0.587) + (pixels[index + 2] * 0.114));
  }
  if (!state.previousVisualSample) {
    state.previousVisualSample = sample;
    state.visualSkipStreak = 0;
    state.visualLowChangeStreak = 0;
    return { changed: true, averageDelta: 255, changedRatio: 1, sample };
  }
  let deltaTotal = 0;
  let changedPixels = 0;
  for (let index = 0; index < sample.length; index += 1) {
    const delta = Math.abs(sample[index] - state.previousVisualSample[index]);
    deltaTotal += delta;
    if (delta >= visualDeltaThreshold) {
      changedPixels += 1;
    }
  }
  const averageDelta = deltaTotal / sample.length;
  const changedRatio = changedPixels / sample.length;
  const changed = averageDelta >= visualAverageDeltaThreshold || changedRatio >= visualChangedRatioThreshold;
  return { changed, averageDelta, changedRatio, sample };
}

function shouldCaptureVisualFrame(state: CaptureState, change: VisualChange) {
  if (change.changed) {
    commitVisualSample(state, change);
    state.visualSkipStreak = 0;
    state.visualLowChangeStreak = 0;
    return { capture: true, reason: `visual_change ${formatChangedRatio(change.changedRatio)} pixels changed` };
  }

  state.visualSkipStreak = (state.visualSkipStreak ?? 0) + 1;
  const hasTinyMotion = change.changedRatio >= visualLowChangeRatioThreshold || change.averageDelta >= 0.04;
  if (hasTinyMotion) {
    state.visualLowChangeStreak = (state.visualLowChangeStreak ?? 0) + 1;
    if (state.visualLowChangeStreak >= visualLowChangeProbeFrames) {
      commitVisualSample(state, change);
      state.visualSkipStreak = 0;
      state.visualLowChangeStreak = 0;
      return { capture: true, reason: `low_change_probe ${formatChangedRatio(change.changedRatio)} pixels changed` };
    }
    return { capture: false, reason: "low_change_wait" };
  }

  state.visualLowChangeStreak = 0;
  if (state.visualSkipStreak >= visualIdleProbeFrames) {
    commitVisualSample(state, change);
    state.visualSkipStreak = 0;
    return { capture: true, reason: "idle_probe" };
  }
  return { capture: false, reason: "idle_frame" };
}

function commitVisualSample(state: CaptureState, change: VisualChange) {
  if (change.sample) {
    state.previousVisualSample = change.sample;
  }
}

function formatChangedRatio(value: number) {
  return `${Math.round(value * 10000) / 100}%`;
}

function captureReadinessIssue(selectedSource: CaptureSource, sources: CaptureSource[]) {
  const hasElectronBridge = Boolean(window.watcher?.getCaptureSources);
  const canUseBrowserPicker = Boolean(navigator.mediaDevices?.getDisplayMedia);
  if (hasElectronBridge && sources.length === 1 && sources[0].id === browserCaptureSource.id) {
    return "The desktop shell did not return any screen or window sources. Restart Watcher with .\\start.ps1.";
  }
  if (selectedSource.id === browserCaptureSource.id && !canUseBrowserPicker) {
    return hasElectronBridge
      ? "Choose a desktop screen or window source instead of the browser picker."
      : "This browser preview cannot capture screens. Use the Watcher desktop window launched by .\\start.ps1.";
  }
  return "";
}

function friendlyCaptureError(error: unknown, sources: CaptureSource[]) {
  const message = error instanceof Error ? error.message : String(error);
  const normalized = message.toLowerCase();
  const hasElectronSources = sources.some((source) => source.id !== browserCaptureSource.id);
  if (normalized.includes("not supported") || normalized.includes("not allowed by the user agent")) {
    return hasElectronSources
      ? "The selected desktop source was not accepted. Choose a screen source and try again."
      : "This browser preview cannot capture screens. Use the Watcher desktop window launched by .\\start.ps1.";
  }
  if (normalized.includes("permission") || normalized.includes("notallowed") || normalized.includes("denied")) {
    return "Screen capture permission was denied. Start again and choose a screen or window.";
  }
  if (normalized.includes("notfound")) {
    return "No capturable screen or window was found. Refresh sources or restart Watcher.";
  }
  return message || "Unknown capture error.";
}

function capturePhaseLabel(phase: CapturePhase) {
  const labels: Record<CapturePhase, string> = {
    idle: "Idle",
    requesting: "Requesting permission",
    starting: "Starting session",
    capturing: "Capturing",
    processing: "Processing frame",
    paused: "Paused",
    stopping: "Stopping",
    error: "Error"
  };
  return labels[phase];
}

function captureHeadline(phase: CapturePhase, active: boolean) {
  if (phase === "requesting") return "Waiting for screen permission";
  if (phase === "starting") return "Starting live capture session";
  if (phase === "processing") return "Processing frame with OCR";
  if (phase === "paused") return "Capture paused";
  if (phase === "stopping") return "Stopping capture";
  if (phase === "error") return "Capture needs attention";
  if (active || phase === "capturing") return "Capture active";
  return "Ready for a user-controlled session";
}

function captureDetail(phase: CapturePhase, stats: CaptureStats) {
  if (phase === "requesting") return "Choose a screen or window in the capture picker.";
  if (phase === "starting") return "Creating the session and preparing the first OCR pass.";
  if (phase === "processing") return `Frame ${stats.framesAttempted} is being hashed, OCR'd, redacted, and discarded.`;
  if (phase === "paused") return "Capture is paused. Resume to continue processing frames.";
  if (phase === "error") return stats.lastReason || "The last capture action failed.";
  if (stats.framesAttempted > 0) {
    return `${stats.eventsStored} event(s) stored, ${stats.framesSkipped} skipped, ${stats.errors} error(s). Last: ${stats.lastAction}${stats.lastReason ? ` (${stats.lastReason})` : ""}.`;
  }
  return "Raw frames are hashed, OCR'd, redacted, converted into structured events, then discarded.";
}

function uiModelProvider(value: string) {
  const normalized = value.trim().toLowerCase();
  if (["onnx-phi", "onnx-phi-reasoning", "phi-onnx", "local-onnx"].includes(normalized)) {
    return "onnx-phi";
  }
  if (["lmstudio", "lm-studio"].includes(normalized)) {
    return "lmstudio";
  }
  if (normalized === "ollama") {
    return "ollama";
  }
  return "onnx-phi";
}

function uiOcrProvider(value: string) {
  const normalized = value.trim().toLowerCase();
  if (["paddle", "paddleocr"].includes(normalized)) {
    return "paddle";
  }
  return "paddle";
}
