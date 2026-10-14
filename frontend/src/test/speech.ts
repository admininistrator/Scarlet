/**
 * Web Speech gia cho test — T-8.4. jsdom khong co `SpeechRecognition` lan
 * `speechSynthesis` (giong Firefox o ve thu nhat), nen moi ca can ho tro phai
 * cai ban gia nay; `vi.unstubAllGlobals()` cua `setup.ts` go sau moi ca.
 */
import { vi } from "vitest";

type ResultEvent = { resultIndex: number; results: { isFinal: boolean; 0: { transcript: string } }[] };

export class FakeRecognition {
  static instances: FakeRecognition[] = [];
  lang = "";
  continuous = false;
  interimResults = false;
  onresult: ((e: ResultEvent) => void) | null = null;
  onerror: ((e: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;
  private started = false;
  // Nhu trinh duyet that: `start()` lan hai tren cung mot recognition nem (B-260).
  start = vi.fn(() => {
    if (this.started) {
      throw new DOMException("already started", "InvalidStateError");
    }
    this.started = true;
  });
  stop = vi.fn(() => this.onend?.());
  abort = vi.fn(() => {
    this.onerror?.({ error: "aborted" });
    this.onend?.();
  });

  constructor() {
    FakeRecognition.instances.push(this);
  }

  hear(transcript: string, isFinal: boolean): void {
    this.onresult?.({ resultIndex: 0, results: [{ isFinal, 0: { transcript } }] });
  }

  fail(error: string): void {
    this.onerror?.({ error });
    this.onend?.();
  }
}

export function installRecognition(): void {
  FakeRecognition.instances = [];
  vi.stubGlobal("SpeechRecognition", FakeRecognition);
}

export class FakeUtterance {
  lang = "";
  voice: SpeechSynthesisVoice | null = null;
  onend: (() => void) | null = null;
  onerror: ((e: { error: string }) => void) | null = null;
  constructor(public text: string) {}
}

/** `cancel()` ban "interrupted" len cau dang doc — dung nhu Chromium. */
export function installSynthesis(voices: Partial<SpeechSynthesisVoice>[] = []) {
  let current: FakeUtterance | null = null;
  const synth = {
    speak: vi.fn((u: FakeUtterance) => {
      current = u;
    }),
    cancel: vi.fn(() => {
      const u = current;
      current = null;
      u?.onerror?.({ error: "interrupted" });
    }),
    getVoices: vi.fn(() => voices),
  };
  vi.stubGlobal("speechSynthesis", synth);
  vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
  return synth;
}
