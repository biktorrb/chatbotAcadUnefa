import logging
import os
import io
from dotenv import load_dotenv
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)
import firebase_admin
from firebase_admin import credentials, firestore
import pandas as pd

load_dotenv()

# Habilitar logging para depuración
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- CONFIGURACIÓN DE FIREBASE ---
try:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    logger.info("Conexión con Firebase establecida correctamente.")
except Exception as e:
    logger.error(f"Error al inicializar Firebase: {e}")
    db = None

# --- DEFINICIÓN DE ESTADOS DE CONVERSACIÓN UNIFICADOS ---
(
    # Flujo de selección de rol inicial
    SELECT_ROLE,
    # Flujo del estudiante
    GET_NAME, GET_ID, GET_CAREER, GET_SUBJECT,
    PART1_Q1, PART1_Q2, PART2_Q1, PART2_Q2,
    PART3_Q1, PART3_Q2, PART3_Q3, PART3_Q4,
    # Flujo del profesor
    PROF_LOGIN_ID, PROF_LOGIN_PASS, PROF_MENU, PROF_UPLOAD_LIST
) = range(17)

# --- DATOS DE LA PRUEBA Y CONFIGURACIÓN ---
QUESTIONS = {
    "part1": [
        {"text": "Pregunta 1 (Selección Simple - 2 puntos):\nEs la acción de intercambiar y de compartir vivencias culturales, ideas, entre otras.","options": [("Intercambio comunitario", "p1q1_correct"),("Comunicación", "p1q1_incorrect1"),("Comunidad y Familia", "p1q1_incorrect2"),], "correct_answer_text": "Intercambio comunitario", "points": 2},
        {"text": "Pregunta 2 (Selección Simple - 2 puntos):\nSe refiera a la forma en que un grupo social utiliza el lenguaje en situaciones comunicativas cotidianas.","options": [("Lenguaje", "p1q2_incorrect1"),("Uso Lingüisticos", "p1q2_correct"),("Convenciones lingüisticas", "p1q2_incorrect2"),], "correct_answer_text": "Uso Lingüisticos", "points": 2},
    ],
    "part2": [
        {"text": "Pregunta 1 (Completación - 3 puntos):\nVenezuela tiene una caracteristica muy importante que comparte con varios paises, vecinos... uno de ellos son las: ________","options": [("Expresiones Coloquiales", "p2q1_incorrect1"),("Expresiones Lexicales", "p2q1_incorrect2"),("Expresiones Llaneras", "p2q1_correct"),], "correct_answer_text": "Expresiones Llaneras", "points": 3},
        {"text": "Pregunta 2 (Completación - 3 puntos):\nEl lenguaje es la base de la comunicación del ser humano... vamos a construir e interpretrar:______","options": [("Importancia de la comunicación", "p2q2_incorrect1"),("Concepto de lenguaje", "p2q2_incorrect2"),("Importancia del lenguaje", "p2q2_correct"),], "correct_answer_text": "Importancia del lenguaje", "points": 3},
    ],
    "part3": [
        {"text": "Pregunta 1 (V/F - 2 puntos):\nLos escritores que aboradan temas de identidad y pensamiento social suelen evitar criticas sobre la sociedad en sus obras.","options": [("Verdadero", "p3q1_incorrect"), ("Falso", "p3q1_correct")], "correct_answer_text": "Falso", "points": 2},
        {"text": "Pregunta 2 (V/F - 2 puntos):\nLas metaforas y paradojas son recursos estilisticos que ayudan a transmitir ideas profundas sobre la sociedad.","options": [("Verdadero", "p3q2_correct"), ("Falso", "p3q2_incorrect")], "correct_answer_text": "Verdadero", "points": 2},
        {"text": "Pregunta 3 (V/F - 2 puntos):\nEl impacto de una obra en la sociedad depende exclusivamente de la calidad literaria del texto...","options": [("Verdadero", "p3q3_incorrect"), ("Falso", "p3q3_correct")], "correct_answer_text": "Falso", "points": 2},
        {"text": "Pregunta 4 (V/F - 2 puntos):\nEl dialogo entre literatura y sociedad es dinamico...","options": [("Verdadero", "p3q4_correct"), ("Falso", "p3q4_incorrect")], "correct_answer_text": "Verdadero", "points": 2},
    ],
}

# --- FUNCIONES DE INICIO Y SELECCIÓN DE ROL ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Inicia la conversación y pregunta el rol del usuario."""
    keyboard = [
        [InlineKeyboardButton("Soy Estudiante", callback_data='role_student')],
        [InlineKeyboardButton("Soy Profesor", callback_data='role_professor')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("¡Bienvenido/a! Por favor, selecciona tu rol:", reply_markup=reply_markup)
    return SELECT_ROLE

async def select_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Dirige al usuario al flujo correcto según el rol seleccionado."""
    query = update.callback_query
    await query.answer()
    
    role = query.data
    context.user_data.clear()

    if role == 'role_student':
        await query.edit_message_text(text="Has seleccionado: Estudiante.\n\nIniciemos la prueba. Por favor, escribe tu nombre completo:")
        return GET_NAME
    elif role == 'role_professor':
        await query.edit_message_text(text="Has seleccionado: Profesor.\n\nIniciemos el acceso al panel. Por favor, introduce tu cédula:")
        return PROF_LOGIN_ID
    
    return ConversationHandler.END

# --- FUNCIONES DEL FLUJO DE ESTUDIANTE ---

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["score"] = 2
    context.user_data["answers"] = {}
    context.user_data["current_part"] = "part1"
    context.user_data["current_question_index"] = 0
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Gracias. Ahora, introduce tu número de cédula (solo números):")
    return GET_ID

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    student_id = update.message.text
    if not student_id.isdigit() or not (7 <= len(student_id) <= 8):
        await update.message.reply_text("Cédula no válida. Ingrésala de nuevo (7 u 8 números).")
        return GET_ID

    if not db:
        await update.message.reply_text("Error de conexión con la base de datos. Inténtalo más tarde.")
        return ConversationHandler.END

    try:
        student_ref = db.collection('students').document(student_id)
        if not student_ref.get().exists:
            await update.message.reply_text("Tu cédula no se encuentra en la lista de estudiantes autorizados.")
            return ConversationHandler.END

        exam_ref = db.collection('exams').document(student_id)
        if exam_ref.get().exists:
            await update.message.reply_text("Ya has presentado esta prueba anteriormente.")
            return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error al validar CI {student_id}: {e}")
        await update.message.reply_text("Error al verificar tus datos. Inténtalo más tarde.")
        return ConversationHandler.END

    context.user_data["id"] = student_id
    logger.info(f"Cédula de estudiante validada: {student_id}")

    try:
        careers_ref = db.collection('carreras').stream()
        keyboard = []
        for career_doc in careers_ref:
            career_data = career_doc.to_dict()
            career_name = career_data.get('nombre', career_doc.id)
            keyboard.append([InlineKeyboardButton(career_name, callback_data=career_name)])
        
        if not keyboard:
            await update.message.reply_text("No se encontraron carreras. Contacta al profesor.")
            return ConversationHandler.END
        
        await update.message.reply_text("Datos validados. Ahora, selecciona tu carrera:", reply_markup=InlineKeyboardMarkup(keyboard))
        return GET_CAREER
    except Exception as e:
        logger.error(f"Error al obtener carreras: {e}")
        await update.message.reply_text("No se pudieron cargar las carreras. Intenta de nuevo.")
        return ConversationHandler.END

async def select_career(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["carrera"] = query.data
    await query.edit_message_text(text=f"Carrera seleccionada: {query.data}")
    await query.message.reply_text("Indica la asignatura:")
    return GET_SUBJECT

async def get_subject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["tema"] = update.message.text
    await update.message.reply_text("Datos completos. ¡Comienza la prueba!")
    return await ask_question(update, context)

async def ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    part_key = context.user_data.get("current_part")
    q_idx = context.user_data.get("current_question_index", 0)

    if not part_key or q_idx >= len(QUESTIONS.get(part_key, [])):
        next_part = {"part1": "part2", "part2": "part3"}.get(part_key)
        if next_part:
            context.user_data["current_part"] = next_part
            context.user_data["current_question_index"] = 0
            return await ask_question(update, context)
        else:
            await (update.callback_query.message if update.callback_query else update.message).edit_text("Calculando resultados...")
            return await end_test(update, context, from_callback=bool(update.callback_query))

    q_data = QUESTIONS[part_key][q_idx]
    keyboard = [[InlineKeyboardButton(opt, callback_data=cb)] for opt, cb in q_data["options"]]
    markup = InlineKeyboardMarkup(keyboard)

    target = update.callback_query.message if update.callback_query else update.message
    if update.callback_query:
        await target.edit_text(q_data["text"], reply_markup=markup)
    else:
        await target.reply_text(q_data["text"], reply_markup=markup)

    state_map = {"part1": PART1_Q1, "part2": PART2_Q1, "part3": PART3_Q1}
    return state_map[part_key] + q_idx

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    query = update.callback_query
    await query.answer()
    part_key = context.user_data["current_part"]
    q_idx = context.user_data["current_question_index"]
    q_data = QUESTIONS[part_key][q_idx]
    
    is_correct = query.data.endswith("_correct")
    if is_correct: context.user_data["score"] += q_data["points"]
    
    selected_option_text = next((opt for opt, cb in q_data["options"] if cb == query.data), "N/A")
    context.user_data["answers"][f"{part_key}_q{q_idx + 1}"] = {
        "question_text": q_data["text"], "selected_option": selected_option_text,
        "correct_option": q_data["correct_answer_text"], "is_correct": is_correct
    }
    context.user_data["current_question_index"] += 1
    return await ask_question(update, context)


async def end_test(update: Update, context: ContextTypes.DEFAULT_TYPE, from_callback: bool=False) -> int:
    user_data = context.user_data
    correct_answers = sum(1 for details in user_data.get("answers", {}).values() if details.get("is_correct"))
    total_questions = sum(len(q_list) for q_list in QUESTIONS.values())
    
    exam_data = {
        "nombre": user_data.get("name"), "estudiante_cedula": user_data.get("id"),
        "carrera": user_data.get("carrera"), "tema": user_data.get("subject"),
        "puntuacion": user_data.get("score"), "respuestas_correctas": correct_answers,
        "total_preguntas": total_questions, "respuestas": user_data.get("answers"),
        "fecha_presentacion": datetime.now()
    }
    if db:
        try: db.collection('exams').document(user_data['id']).set(exam_data)
        except Exception as e: logger.error(f"Error guardando examen {user_data['id']}: {e}")

    summary = (
        f"¡Prueba Finalizada!\n\nResumen para {user_data.get('name')}:\n"
        f"Cédula: {user_data.get('id')}\nCarrera: {user_data.get('carrera')}\n"
        f"Asignatura: {user_data.get('tema')}\n\n"
        f"Respuestas Correctas: {correct_answers} de {total_questions}\n"
        f"Puntuación Total: {user_data.get('score', 0)} puntos.\n\n"
        "Tus resultados han sido guardados."
    )
    await (update.callback_query.message if from_callback else update.message).reply_text(summary)
    return ConversationHandler.END


# --- FUNCIONES DEL FLUJO DE PROFESOR ---

async def prof_get_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['prof_id'] = update.message.text
    await update.message.reply_text("Introduce tu contraseña:")
    return PROF_LOGIN_PASS

async def prof_get_password_and_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    prof_id = context.user_data.get('prof_id')
    password = update.message.text

    if not db:
        await update.message.reply_text("Error de conexión con la base de datos.")
        return ConversationHandler.END
        
    try:
        prof_ref = db.collection('professors').document(prof_id)
        prof_doc = prof_ref.get()
        if prof_doc.exists and prof_doc.to_dict().get('pass') == password:
            logger.info(f"Profesor {prof_id} autenticado.")
            keyboard = [
                [InlineKeyboardButton("Cargar Lista de Alumnos (.xlsx)", callback_data='upload_students')],
                [InlineKeyboardButton("Descargar Resultados (.xlsx)", callback_data='download_results')],
            ]
            await update.message.reply_text("Autenticación exitosa. ¿Qué deseas hacer?", reply_markup=InlineKeyboardMarkup(keyboard))
            return PROF_MENU
        else:
            await update.message.reply_text("Cédula o contraseña incorrecta.")
            return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error en auth de profesor {prof_id}: {e}")
        await update.message.reply_text("Ocurrió un error al iniciar sesión.")
        return ConversationHandler.END


async def prof_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == 'upload_students':
        await query.edit_message_text(text="Sube el archivo Excel (.xlsx) con una columna llamada 'cedula'.")
        return PROF_UPLOAD_LIST
    elif query.data == 'download_results':
        await query.edit_message_text(text="Generando archivo de resultados... por favor espera.")
        return await prof_download_results(update, context)

async def prof_upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    document = update.message.document
    if not document.file_name.endswith('.xlsx'):
        await update.message.reply_text("Formato incorrecto. Sube un .xlsx")
        return PROF_UPLOAD_LIST

    try:
        file = await context.bot.get_file(document.file_id)
        file_content = io.BytesIO()
        await file.download_to_memory(file_content)
        
        df = pd.read_excel(file_content)
        if 'cedula' not in df.columns:
            await update.message.reply_text("El archivo no tiene la columna 'cedula'.")
            return PROF_UPLOAD_LIST

        batch = db.batch()
        count = 0
        for cedula in df['cedula']:
            student_id = str(cedula).strip()
            if student_id.isdigit():
                doc_ref = db.collection('students').document(student_id)
                batch.set(doc_ref, {
                                    'authorized': True, 
                                    'loaded_by': context.user_data.get('prof_id')})
                count += 1
        
        batch.commit()
        await update.message.reply_text(f"Proceso completado. Se cargaron {count} estudiantes.")

    except Exception as e:
        logger.error(f"Error procesando archivo de estudiantes: {e}")
        await update.message.reply_text("Ocurrió un error al procesar el archivo.")
        
    return ConversationHandler.END


async def prof_download_results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        exams_ref = db.collection('exams').stream()
        results_data = [doc.to_dict() for doc in exams_ref]
        if not results_data:
            await update.callback_query.message.reply_text("Aún no hay resultados para descargar.")
            return ConversationHandler.END

        df = pd.DataFrame(results_data)
        if 'fecha_presentacion' in df.columns: df['fecha_presentacion'] = pd.to_datetime(df['fecha_presentacion']).dt.strftime('%Y-%m-%d %H:%M:%S')
        if 'answers' in df.columns: del df['answers']

        output = io.BytesIO()
        df.to_excel(output, index=False, sheet_name='Resultados')
        output.seek(0)
        
        await context.bot.send_document(chat_id=update.effective_chat.id, document=output, filename=f"resultados_{datetime.now().strftime('%Y%m%d')}.xlsx")
    except Exception as e:
        logger.error(f"Error generando resultados: {e}")
        await update.callback_query.message.reply_text("Ocurrió un error al generar el archivo.")

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancela la operación actual."""
    await update.message.reply_text("Operación cancelada. Escribe /start para comenzar de nuevo.")
    context.user_data.clear()
    return ConversationHandler.END

def main() -> None:
    """Inicia el bot y configura el handler unificado."""
    application = Application.builder().token(os.getenv("BOT_TOKEN")).build()

    # Conversation handler unificado para todos los flujos
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            # Selección de Rol
            SELECT_ROLE: [CallbackQueryHandler(select_role, pattern='^role_')],
            # Flujo Estudiante
            GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            GET_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_id)],
            GET_CAREER: [CallbackQueryHandler(select_career)],
            GET_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_subject)],
            PART1_Q1: [CallbackQueryHandler(handle_answer, pattern="^p1q1_")],
            PART1_Q2: [CallbackQueryHandler(handle_answer, pattern="^p1q2_")],
            PART2_Q1: [CallbackQueryHandler(handle_answer, pattern="^p2q1_")],
            PART2_Q2: [CallbackQueryHandler(handle_answer, pattern="^p2q2_")],
            PART3_Q1: [CallbackQueryHandler(handle_answer, pattern="^p3q1_")],
            PART3_Q2: [CallbackQueryHandler(handle_answer, pattern="^p3q2_")],
            PART3_Q3: [CallbackQueryHandler(handle_answer, pattern="^p3q3_")],
            PART3_Q4: [CallbackQueryHandler(handle_answer, pattern="^p3q4_")],
            # Flujo Profesor
            PROF_LOGIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, prof_get_id)],
            PROF_LOGIN_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, prof_get_password_and_auth)],
            PROF_MENU: [CallbackQueryHandler(prof_menu_handler)],
            PROF_UPLOAD_LIST: [MessageHandler(filters.Document.ALL, prof_upload_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
    )

    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == "__main__":
    main()
