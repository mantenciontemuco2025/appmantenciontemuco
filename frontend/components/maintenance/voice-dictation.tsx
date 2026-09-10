"use client";

import { useEffect, useRef, useState } from "react";
import { Mic, MicOff } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Voice dictation as progressive enhancement.
 *
 * If the Web Speech API is available, allow start/stop dictation and
 * write the transcript into the textarea. The worker can always review
 * and edit the text before confirming.
 *
 * If not available, the form works normally and we show a small note.
 */

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: { results: { [i: number]: { [j: number]: { transcript: string } }; length: number } }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
};

export function VoiceDictation({
  onTranscript,
  disabled,
}: {
  onTranscript: (text: string) => void;
  disabled?: boolean;
}) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [middleware, setMiddleware] = useState<string | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    const SpeechRecognition =
      (window as unknown as Record<string, unknown>)["SpeechRecognition"] ||
      (window as unknown as Record<string, unknown>)["webkitSpeechRecognition"];
    if (SpeechRecognition) {
      const RecognitionCtor = SpeechRecognition as new () => SpeechRecognitionLike;
      const rec = new RecognitionCtor();
      rec.lang = "es-ES";
      rec.continuous = true;
      rec.interimResults = false;
      rec.onresult = (event) => {
        let transcript = "";
        for (let i = 0; i < event.results.length; i++) {
          transcript += event.results[i][0].transcript;
        }
        onTranscript(transcript.trim());
      };
      rec.onend = () => setListening(false);
      rec.onerror = () => setListening(false);
      recognitionRef.current = rec;
      setSupported(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function toggle() {
    const rec = recognitionRef.current;
    if (!rec) return;
    if (listening) {
      rec.stop();
      setListening(false);
    } else {
      setMiddleware(null);
      try {
        rec.start();
        setListening(true);
      } catch {
        setMiddleware("No se pudo iniciar el dictado. Intente de nuevo.");
      }
    }
  }

  if (!supported) {
    return (
      <p className="text-xs text-muted-foreground">
        🎤 Tu navegador no soporta dictado por voz.
      </p>
    );
  }

  return (
    <div className="space-y-1.5">
      <Button
        type="button"
        variant={listening ? "destructive" : "secondary"}
        size="lg"
        className="w-full"
        onClick={toggle}
        disabled={disabled}
      >
        {listening ? (
          <>
            <MicOff className="mr-2 h-5 w-5" />
            Detener dictado (escuchando...)
          </>
        ) : (
          <>
            <Mic className="mr-2 h-5 w-5" />
            Dictar por voz
          </>
        )}
      </Button>
      {listening && (
        <p className="flex items-center gap-2 text-sm text-emerald-600">
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-emerald-500 animate-pulse" />
          Escuchando... hable con claridad
        </p>
      )}
      {middleware && <p className="text-xs text-destructive">{middleware}</p>}
    </div>
  );
}
