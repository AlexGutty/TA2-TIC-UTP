import streamlit as st
from groq import Groq
from dotenv import load_dotenv
import streamlit.components.v1 as components
import base64
import json
import os

import agent_tools

# (configuracion de la pagina - debe ir primero, antes de cualquier otro comando st.)
st.set_page_config(
    page_title="Chatbot TIC",
    page_icon="🤖",
    layout="centered",
    initial_sidebar_state="expanded"
)

# (cargar la API key desde el archivo .env)
load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# (funcion para cargar el CSS externo)
def load_css(file_path):
    with open(file_path) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# (ahora se carga desde el mismo archivo que usa el widget de voz,
# asi solo existe una copia de todos los estilos)
load_css("voice_widget/frontend/styles.css")

# (registrar el componente de entrada unificado: texto + voz)
_chat_bar_component = components.declare_component(
    "chat_bar",
    path="voice_widget/frontend"
)

def chat_bar(key=None, prefill_token=None, prefill_text="", prefill_done=True):
    return _chat_bar_component(
        key=key,
        prefill_token=prefill_token,
        prefill_text=prefill_text,
        prefill_done=prefill_done,
        default=None
    )

# (construye los mensajes que se le mandan al modelo, inyectando el
# contexto de la cita cuando un mensaje fue enviado como "respuesta a",
# y anteponiendo siempre el prompt de sistema del agente)
def build_api_messages(messages):
    api_messages = [{"role": "system", "content": agent_tools.SYSTEM_PROMPT}]

    region = st.session_state.get("region_seleccionada")
    tiene_region = region and region != "(todas)"

    # (indice del ULTIMO mensaje de usuario -- solo ahi se inyecta la region
    # activa, pegada a la pregunta actual. Ponerla solo en el prompt de
    # sistema no funciona bien: compite en peso contra todo el historial
    # de la conversacion, y el modelo tiende a seguir con la region de la
    # que ya se hablo antes en vez de la nueva seleccionada en el sidebar)
    ultimo_user_idx = None
    for i, m in enumerate(messages):
        if m["role"] == "user":
            ultimo_user_idx = i

    for i, m in enumerate(messages):
        content = m["content"]
        if m.get("reply_context"):
            content = f'(El usuario esta respondiendo a este mensaje previo: "{m["reply_context"]}")\n\n{content}'
        if i == ultimo_user_idx and tiene_region:
            content = (
                f"(Region actualmente seleccionada en la interfaz: {region}. "
                f"Usa esta region si mi pregunta no menciona una region distinta "
                f"explicitamente, sin importar de que region se hablo antes en esta conversacion.)\n\n{content}"
            )
        api_messages.append({"role": m["role"], "content": content})
    return api_messages

# (sidebar con informacion y boton de nuevo chat)
with st.sidebar:
    st.markdown("### 🩺 Gestor de Brechas de Salud")
    st.caption("Powered by Groq · Llama / GPT-OSS")
    if st.button("➕ Nuevo chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    st.divider()

    st.selectbox(
        "Región a monitorear",
        options=["(todas)"] + agent_tools.REGIONES,
        key="region_seleccionada",
        help="El agente usara esta region si no especificas otra en tu pregunta.",
    )

    st.divider()
    st.caption("Curso: Herramientas de Desarrollo Profesional - TIC")
    st.caption("Fuente de datos: SUSALUD (Formato F500.2) · Automatizacion: Trello")

st.title("🩺 Gestor de Brechas de Salud")
st.caption("Agente de IA para monitoreo de ocupacion UCI — ODS 3: Salud y bienestar")

# (inicializar el historial de mensajes si no existe)
if "messages" not in st.session_state:
    st.session_state.messages = []

# (rastrear el ultimo nonce procesado, para no reenviar el mismo mensaje en cada rerun)
if "last_nonce" not in st.session_state:
    st.session_state.last_nonce = None

# (estado de la transcripcion en vivo por fragmentos)
if "prefill_token" not in st.session_state:
    st.session_state.prefill_token = 0
if "prefill_text" not in st.session_state:
    st.session_state.prefill_text = ""
if "prefill_done" not in st.session_state:
    st.session_state.prefill_done = True
if "current_recording_id" not in st.session_state:
    st.session_state.current_recording_id = None
if "live_transcript" not in st.session_state:
    st.session_state.live_transcript = ""

# (mensaje al que se esta respondiendo actualmente, si hay uno)
if "replying_to" not in st.session_state:
    st.session_state.replying_to = None

# (estado del reproductor de voz: que mensaje esta "activo" y si esta pausado)
if "tts_active_idx" not in st.session_state:
    st.session_state.tts_active_idx = None
if "tts_is_paused" not in st.session_state:
    st.session_state.tts_is_paused = False
if "pending_tts_command" not in st.session_state:
    st.session_state.pending_tts_command = None

# (contenedor reservado para el historial de mensajes - se dibuja ANTES que la barra fija)
messages_container = st.container()

with messages_container:
    for i, msg in enumerate(st.session_state.messages):
        avatar = "🧑" if msg["role"] == "user" else "🤖"
        with st.chat_message(msg["role"], avatar=avatar):

            # (si este mensaje fue enviado como respuesta a otro, muestra
            # la cita como referencia pequena encima del texto)
            if msg.get("reply_context"):
                quote = msg["reply_context"]
                if len(quote) > 120:
                    quote = quote[:120].rstrip() + "..."
                st.markdown(f'<div class="reply-quote">{quote}</div>', unsafe_allow_html=True)

            st.markdown(msg["content"])

            # (botones de responder / escuchar solo debajo de las respuestas del bot)
            if msg["role"] == "assistant":
                col_reply, col1, col2, col3, _ = st.columns([1, 1, 1, 1, 8])

                with col_reply:
                    if st.button("↩️", key=f"reply_{i}", help="Responder a este mensaje"):
                        st.session_state.replying_to = msg["content"]
                        st.rerun()

                if st.session_state.tts_active_idx == i:
                    with col1:
                        toggle_label = "▶️" if st.session_state.tts_is_paused else "⏸️"
                        toggle_help = "Reanudar" if st.session_state.tts_is_paused else "Pausar"
                        if st.button(toggle_label, key=f"toggle_tts_{i}", help=toggle_help):
                            if st.session_state.tts_is_paused:
                                st.session_state.pending_tts_command = {"action": "resume"}
                                st.session_state.tts_is_paused = False
                            else:
                                st.session_state.pending_tts_command = {"action": "pause"}
                                st.session_state.tts_is_paused = True
                            st.rerun()

                    with col2:
                        if st.button("🔁", key=f"restart_tts_{i}", help="Reiniciar audio"):
                            st.session_state.pending_tts_command = {
                                "action": "restart",
                                "text": msg["content"]
                            }
                            st.session_state.tts_is_paused = False
                            st.rerun()

                    with col3:
                        if st.button("⏹️", key=f"stop_tts_{i}", help="Detener"):
                            st.session_state.pending_tts_command = {"action": "stop"}
                            st.session_state.tts_active_idx = None
                            st.session_state.tts_is_paused = False
                            st.rerun()
                else:
                    with col1:
                        if st.button("🔊", key=f"listen_{i}", help="Escuchar en voz alta"):
                            st.session_state.tts_active_idx = i
                            st.session_state.tts_is_paused = False
                            st.session_state.pending_tts_command = {
                                "action": "play",
                                "text": msg["content"]
                            }
                            st.rerun()

# (barra de entrada unificada: texto y voz en el mismo componente)
with st.container(key="input_bar"):

    # (chip que muestra a que mensaje se esta respondiendo, con boton para cancelar)
    if st.session_state.replying_to:
        preview = st.session_state.replying_to
        if len(preview) > 90:
            preview = preview[:90].rstrip() + "..."

        chip_col, x_col = st.columns([11, 1])
        with chip_col:
            st.markdown(
                f'<div class="reply-chip">↩️ Respondiendo a: <span>{preview}</span></div>',
                unsafe_allow_html=True
            )
        with x_col:
            if st.button("✕", key="cancel_reply", help="Cancelar respuesta"):
                st.session_state.replying_to = None
                st.rerun()

    result = chat_bar(
        key="chat_bar",
        prefill_token=st.session_state.prefill_token,
        prefill_text=st.session_state.prefill_text,
        prefill_done=st.session_state.prefill_done
    )

# (si hay un comando de audio pendiente, se lo mandamos a la instancia de
# speechSynthesis de la VENTANA PRINCIPAL (window.parent), no de este iframe
# temporal - asi la reproduccion sigue viva aunque Streamlit vuelva a
# ejecutar el script en el siguiente boton que se presione)
if st.session_state.pending_tts_command:
    cmd = st.session_state.pending_tts_command
    action_js = json.dumps(cmd.get("action"))
    text_js = json.dumps(cmd.get("text", ""))
    components.html(
        f"""
        <script>
        const synth = window.parent.speechSynthesis;
        const action = {action_js};

        if (action === "play" || action === "restart") {{
            synth.cancel();
            const utter = new SpeechSynthesisUtterance({text_js});
            utter.lang = "es-PE";
            synth.speak(utter);
        }} else if (action === "pause") {{
            synth.pause();
        }} else if (action === "resume") {{
            synth.resume();
        }} else if (action === "stop") {{
            synth.cancel();
        }}
        </script>
        """,
        height=0
    )
    st.session_state.pending_tts_command = None

prompt = None

if result and result.get("nonce") != st.session_state.last_nonce:
    st.session_state.last_nonce = result.get("nonce")
    result_type = result.get("type")

    if result_type == "text":
        prompt = result.get("data", "").strip()

    elif result_type in ("audio_chunk", "audio_done"):
        recording_id = result.get("recording_id")

        if recording_id != st.session_state.current_recording_id:
            st.session_state.current_recording_id = recording_id
            st.session_state.live_transcript = ""

        if result_type == "audio_chunk":
            try:
                audio_bytes = base64.b64decode(result["data"])
                mime = result.get("mime", "audio/webm")
                ext = "webm" if "webm" in mime else "wav"
                transcription = client.audio.transcriptions.create(
                    file=(f"chunk.{ext}", audio_bytes),
                    model="whisper-large-v3-turbo",
                    language="es"
                )
                chunk_text = transcription.text.strip()
                if chunk_text:
                    st.session_state.live_transcript = (
                        st.session_state.live_transcript + " " + chunk_text
                    ).strip()
            except Exception:
                pass

        st.session_state.prefill_text = st.session_state.live_transcript
        st.session_state.prefill_done = result.get("final", False)
        st.session_state.prefill_token += 1
        st.rerun()

if prompt:
    reply_context = st.session_state.replying_to
    st.session_state.replying_to = None

    with messages_container:
        st.session_state.messages.append({
            "role": "user",
            "content": prompt,
            "reply_context": reply_context
        })
        with st.chat_message("user", avatar="🧑"):
            if reply_context:
                quote = reply_context
                if len(quote) > 120:
                    quote = quote[:120].rstrip() + "..."
                st.markdown(f'<div class="reply-quote">{quote}</div>', unsafe_allow_html=True)
            st.markdown(prompt)

        with st.chat_message("assistant", avatar="🤖"):
            api_messages = build_api_messages(st.session_state.messages)

            # (hasta 20 rondas de tool calling: el modelo puede necesitar
            # consultar_ocupacion_uci -> detectar_brecha_critica -> crear_ticket_incidencia
            # en secuencia, y como ahora el ticket se crea automaticamente para
            # CADA hospital en brecha de una region, una region con varios
            # hospitales criticos necesita muchas llamadas seguidas -- 3 rondas
            # se quedaba corto y provocaba el error "Tool choice is none, but
            # model called a tool" al llegar al limite con hospitales pendientes)
            for _ in range(20):
                respuesta = client.chat.completions.create(
                    model="openai/gpt-oss-20b",
                    messages=api_messages,
                    tools=agent_tools.TOOLS,
                    tool_choice="auto",
                )
                mensaje = respuesta.choices[0].message

                if not mensaje.tool_calls:
                    break

                api_messages.append({
                    "role": "assistant",
                    "content": mensaje.content or "",
                    "tool_calls": [tc.model_dump() for tc in mensaje.tool_calls],
                })

                for tool_call in mensaje.tool_calls:
                    nombre = tool_call.function.name

                    with st.status(f"Ejecutando `{nombre}`...", expanded=False) as status:
                        resultado_json = agent_tools.ejecutar_tool_call(tool_call)

                        # (confirmacion visible cuando se crea un ticket real en Trello --
                        # esto es lo que hace visible la automatizacion durante la demo)
                        if nombre == "crear_ticket_incidencia":
                            resultado = json.loads(resultado_json)
                            if resultado.get("creado"):
                                status.update(
                                    label=f"✅ Ticket creado en Trello — {resultado.get('url_ticket')}",
                                    state="complete",
                                )
                            else:
                                status.update(
                                    label=f"⚠️ No se pudo crear el ticket: {resultado.get('error')}",
                                    state="error",
                                )
                        else:
                            status.update(label=f"`{nombre}` completado", state="complete")

                    api_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": resultado_json,
                    })
            else:
                mensaje = respuesta.choices[0].message

            # (si tras las 20 rondas el modelo TODAVIA quiere llamar una
            # herramienta (caso muy raro), se lo pedimos una vez mas sin
            # streaming y SIN mandarle la lista de tools -- si se le manda
            # tool_choice="none" pero SI se le siguen pasando las tools,
            # gpt-oss a veces intenta llamar una igual y Groq responde con
            # el error "Tool choice is none, but model called a tool". Al no
            # recibir ninguna definicion de tools, no tiene nada que llamar.
            # Streaming + tools en Groq con gpt-oss tampoco es confiable
            # apenas hubo tool calls antes en la conversacion -- por eso la
            # respuesta final SIEMPRE se pide sin streaming)
            if mensaje.tool_calls:
                respuesta_final = client.chat.completions.create(
                    model="openai/gpt-oss-20b",
                    messages=api_messages,
                )
                reply = respuesta_final.choices[0].message.content or ""
            else:
                reply = mensaje.content or ""

            # (efecto de escritura simulado localmente, palabra por palabra,
            # ya que la respuesta real ya la tenemos completa)
            def _fake_stream(texto):
                palabras = texto.split(" ")
                for i, palabra in enumerate(palabras):
                    yield palabra + (" " if i < len(palabras) - 1 else "")

            st.write_stream(_fake_stream(reply))

        st.session_state.messages.append({"role": "assistant", "content": reply})

    st.rerun()