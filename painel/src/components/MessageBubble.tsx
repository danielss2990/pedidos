import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { apiBlob } from "../api";
import { time } from "../format";
import type { Message } from "../types";
import { Icon } from "./ui";

const AUTHOR = { cliente: "Cliente", bot: "Bot", atendente: "Atendente" } as const;

/** Busca a mídia com o token (uma tag <img>/<audio> não envia o cabeçalho Authorization). */
function useMediaUrl(conversationId: string, message: Message): string | null {
  const blob = useQuery({
    queryKey: ["media", message.id],
    queryFn: () =>
      apiBlob(`/api/v1/conversations/${conversationId}/messages/${message.id}/media`),
    enabled: !!message.media_path,
    staleTime: Infinity,
    retry: false,
  });
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!blob.data) return;
    const objectUrl = URL.createObjectURL(blob.data);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [blob.data]);
  return url;
}

export default function MessageBubble({
  message,
  conversationId,
}: {
  message: Message;
  conversationId: string;
}) {
  const url = useMediaUrl(conversationId, message);
  const incoming = message.direcao === "entrada";

  let body: ReactNode = message.conteudo;
  if (message.tipo === "audio") {
    body = (
      <>
        {url ? (
          <audio controls src={url} preload="none" />
        ) : (
          <span className="media-placeholder">
            <Icon name="mic" size={16} /> Áudio
          </span>
        )}
        {message.transcricao && <p className="transcript">“{message.transcricao}”</p>}
      </>
    );
  } else if (message.tipo === "imagem") {
    body = (
      <>
        {url ? (
          <a href={url} target="_blank" rel="noreferrer">
            <img src={url} alt="Foto enviada pelo cliente" />
          </a>
        ) : (
          <span className="media-placeholder">
            <Icon name="image" size={16} /> Foto
          </span>
        )}
        {message.conteudo && <p>{message.conteudo}</p>}
      </>
    );
  } else if (message.tipo === "botao" && incoming) {
    body = <em>Tocou em “{message.conteudo}”</em>;
  } else if (!message.conteudo) {
    body = <em className="muted">Conteúdo removido</em>;
  }

  return (
    <div className={`bubble-row ${incoming ? "in" : "out"} by-${message.enviado_por}`}>
      <div className="bubble">
        {!incoming && <span className="author">{AUTHOR[message.enviado_por]}</span>}
        <div className="bubble-content">{body}</div>
        <time dateTime={message.created_at}>{time(message.created_at)}</time>
      </div>
    </div>
  );
}
