import { useCallback, useEffect, useId, useRef, useState, useSyncExternalStore } from "react";

import { t } from "./i18n";

/**
 * Giong noi — T-8.4, ADR-13, §16.2, ban T-HD12 (`useSpeechInput.ts`,
 * `useReadAloud.ts`).
 *
 * KH tham chieu: ADR-13, §16.2, R2, R16, §22.4 · tasks.md T-8.4 · NQ-149.
 *
 * `VoiceProvider` la ranh gioi §16.2: component chi biet `voice.*`, nen thay
 * Web Speech bang Whisper / TTS API sau nay la viet mot ban `VoiceProvider`
 * khac, khong sua `Composer` hay `AnswerActions`.
 *
 * HAI kha nang, HAI phep do (Cam bay ③): Firefox 153 ESR KHONG co
 * `SpeechRecognition` nhung CO `speechSynthesis` (do) ⇒ an mic, giu Doc to.
 * Mot co "voice" chung la sai.
 *
 * Locale BCP-47 lay tu `vi.json` (`voice.locale`, A3).
 */

export type DictationError = "denied" | "noSpeech" | "network" | "other";

export type DictationHandlers = {
  /** Chu tam cua lan nghe — chi de hien, khong vao o nhap. */
  onInterim: (text: string) => void;
  /** Mot doan da chot — noi vao o nhap. */
  onFinal: (text: string) => void;
  onError: (error: DictationError) => void;
  /** Phien nghe ket thuc (tu dung, `stop()`, hoac sau loi). */
  onEnd: () => void;
};

export type Dictation = { stop: () => void; abort: () => void };

export type ReadHandlers = { onEnd: () => void; onError: () => void };

export type VoiceProvider = {
  canDictate: () => boolean;
  /** Bat dau nghe NGAY (goi tu handler bam, khong tu effect — B-260). */
  dictate: (handlers: DictationHandlers) => Dictation;
  canReadAloud: () => boolean;
  /** Huy moi thu dang doc roi doc `text`. `cancel()` cua chinh ta KHONG la loi. */
  readAloud: (text: string, handlers: ReadHandlers) => void;
  stopReading: () => void;
};

/* lib.dom cua TypeScript chua co SpeechRecognition — khai phan dung toi. */
type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};
type RecognitionCtor = new () => Recognition;

function recognitionCtor(): RecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/** Ban T-HD12: `audio-capture` (khong co mic) chung cau voi bi tu choi quyen. */
function dictationError(code: string): DictationError | null {
  switch (code) {
    case "aborted":
      return null; // chinh ta goi `abort()`
    case "not-allowed":
    case "service-not-allowed":
    case "audio-capture":
      return "denied";
    case "no-speech":
      return "noSpeech";
    case "network":
      return "network";
    default:
      return "other";
  }
}

let utterance: SpeechSynthesisUtterance | null = null;

export const webSpeech: VoiceProvider = {
  canDictate: () => recognitionCtor() !== null,

  dictate(handlers) {
    const Ctor = recognitionCtor();
    if (Ctor === null) {
      throw new Error("SpeechRecognition khong co");
    }
    const recognition = new Ctor();
    recognition.lang = t("voice.locale");
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = (e) => {
      let pending = "";
      for (let i = e.resultIndex; i < e.results.length; i += 1) {
        const result = e.results[i];
        const text = result[0].transcript.trim();
        if (!result.isFinal) {
          pending += result[0].transcript;
        } else if (text !== "") {
          handlers.onFinal(text);
        }
      }
      handlers.onInterim(pending.trim());
    };
    recognition.onerror = (e) => {
      const error = dictationError(e.error);
      if (error !== null) {
        handlers.onError(error);
      }
    };
    recognition.onend = handlers.onEnd;
    recognition.start();
    return {
      stop: () => recognition.stop(),
      // Go handler truoc: sau `abort()` khong mot su kien nao duoc cham vao
      // component da roi hoi thoai / da unmount.
      abort: () => {
        recognition.onresult = null;
        recognition.onerror = null;
        recognition.onend = null;
        recognition.abort();
      },
    };
  },

  canReadAloud: () => "speechSynthesis" in window && typeof SpeechSynthesisUtterance === "function",

  readAloud(text, handlers) {
    const synth = window.speechSynthesis;
    // Nha cau cu TRUOC `cancel()`: "interrupted" cua no khong duoc cham vao cau moi.
    utterance = null;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(text);
    const locale = t("voice.locale");
    u.lang = locale;
    // `voiceschanged` co the den muon: chua co giong nao thi de trinh duyet
    // chon theo `lang` (§16.2 "khong thi giong mac dinh").
    const prefix = locale.split("-")[0].toLowerCase();
    const match = synth.getVoices().find((v) => v.lang.toLowerCase().startsWith(prefix));
    if (match !== undefined) {
      u.voice = match;
    }
    // Ca hai su kien: Chromium bao `synthesis-failed` CHI bang `error`, khong
    // `end` (do — 0 giong) ⇒ nghe moi `end` la ket "dang doc".
    u.onend = () => {
      if (utterance === u) {
        utterance = null;
        handlers.onEnd();
      }
    };
    u.onerror = (e) => {
      if (utterance !== u) {
        return;
      }
      utterance = null;
      // `cancel()` cua chinh ta ban "interrupted" / "canceled".
      if (e.error === "interrupted" || e.error === "canceled") {
        handlers.onEnd();
      } else {
        handlers.onError();
      }
    };
    utterance = u;
    synth.speak(u);
  },

  stopReading() {
    utterance = null;
    window.speechSynthesis.cancel();
  },
};

export const voice: VoiceProvider = webSpeech;

/* ══════════════════════════════════════════════════════════════════════════
   Nhap bang giong noi — mot phien = bam mic toi khi bam lai (ban T-HD12).
   ══════════════════════════════════════════════════════════════════════════ */

/**
 * `resetKey` doi (doi hoi thoai) hoac component unmount (roi man) ⇒ `abort()`.
 * Recognition tao trong `toggle` (handler bam), khong trong effect: StrictMode
 * ban doi effect, `start()` lan hai tren cung mot recognition nem
 * `InvalidStateError` (B-260).
 */
export function useDictation(resetKey: unknown, onFinal: (text: string) => void) {
  const [supported] = useState(() => voice.canDictate());
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<DictationError | null>(null);
  const sessionRef = useRef<Dictation | null>(null);
  const onFinalRef = useRef(onFinal);
  onFinalRef.current = onFinal;

  const abort = useCallback(() => {
    const session = sessionRef.current;
    if (session === null) {
      return;
    }
    sessionRef.current = null;
    session.abort();
    setListening(false);
    setInterim("");
  }, []);

  const toggle = useCallback(() => {
    if (sessionRef.current !== null) {
      sessionRef.current.stop();
      return;
    }
    setError(null);
    setInterim("");
    try {
      sessionRef.current = voice.dictate({
        onInterim: setInterim,
        onFinal: (text) => onFinalRef.current(text),
        onError: setError,
        onEnd: () => {
          sessionRef.current = null;
          setListening(false);
          setInterim("");
        },
      });
      setListening(true);
    } catch {
      sessionRef.current = null;
      setError("other");
    }
  }, []);

  useEffect(() => abort, [resetKey, abort]);

  return { supported, listening, interim, error, toggle, abort };
}

export type DictationState = ReturnType<typeof useDictation>;

/* ══════════════════════════════════════════════════════════════════════════
   Doc to — MOT cau tra loi duoc doc mot luc tren toan app.
   ══════════════════════════════════════════════════════════════════════════ */

type ReadStore = { speakingId: string | null; errorId: string | null };
let readStore: ReadStore = { speakingId: null, errorId: null };
const readListeners = new Set<() => void>();

function setReadStore(next: ReadStore): void {
  readStore = next;
  readListeners.forEach((listener) => listener());
}

function subscribeRead(listener: () => void): () => void {
  readListeners.add(listener);
  return () => readListeners.delete(listener);
}

/**
 * `getText` goi luc BAM (chu da render luc ay). Bam cau khac ⇒ cau cu huy
 * (`readAloud` goi `cancel()` truoc), nut cu tu ve "Doc to" qua store chung.
 * Unmount khi dang doc (doi hoi thoai, roi man) ⇒ dung.
 */
export function useReadAloud(getText: () => string) {
  const id = useId();
  const snap = useSyncExternalStore(subscribeRead, () => readStore);
  const supported = voice.canReadAloud();
  const speaking = snap.speakingId === id;

  const toggle = useCallback(() => {
    if (readStore.speakingId === id) {
      setReadStore({ speakingId: null, errorId: null });
      voice.stopReading();
      return;
    }
    const text = getText();
    if (text === "") {
      return;
    }
    setReadStore({ speakingId: id, errorId: null });
    voice.readAloud(text, {
      onEnd: () => readStore.speakingId === id && setReadStore({ speakingId: null, errorId: null }),
      onError: () => readStore.speakingId === id && setReadStore({ speakingId: null, errorId: id }),
    });
  }, [id, getText]);

  useEffect(
    () => () => {
      if (readStore.speakingId === id) {
        setReadStore({ speakingId: null, errorId: null });
        voice.stopReading();
      }
    },
    [id],
  );

  return { supported, speaking, failed: snap.errorId === id, toggle };
}

export type ReadAloudState = ReturnType<typeof useReadAloud>;
