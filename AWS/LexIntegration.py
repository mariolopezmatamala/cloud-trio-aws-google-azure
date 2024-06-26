import json
import boto3
import os

s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('ChatbotResponses')
bucket_name = os.environ['bucket_name']
folder_name = os.environ['folder_name']


def lambda_handler(event, context):
    """
    Función principal de la Lambda que maneja las solicitudes entrantes de Lex.
    
    Parámetros:
    - event: El evento desencadenado por Lex, contiene detalles como la intención y los atributos de la sesión.
    - context: Contexto de la ejecución de la Lambda.

    Retorna:
    - Un diccionario con la respuesta apropiada basada en la intención del usuario.
    """
    intent_name = event['sessionState']['intent']['name']
    session_attributes = event["sessionState"]["sessionAttributes"]

    if intent_name == 'StartTutorial':
        return startTutorial()
    elif intent_name == 'NextStep':
        return nextStep(event)
    elif intent_name == 'RepeatStep':
        return currentStep(event)
    elif intent_name == 'GoToStep':
        return goToStep(event)
    elif intent_name in ['CreacionRolIAM', 'CreacionBucketS3', 'CrearSNS', 'CrearFuncionLambda', 'ExplicacionFuncionesLambda', 'Textract', 'ComprehendTranslate', 'Lex']:
        return handle_question(event)
    else:
        message = "No puedo manejar esa solicitud en este momento."
        return build_response(message, session_attributes, intent_name)
    
def startTutorial():
    """
    Inicia el tutorial configurando los atributos iniciales de la sesión y devolviendo un mensaje de bienvenida.

    Parámetros:
    - Ninguno.

    Retorna:
    - Un diccionario con el mensaje de bienvenida y los atributos de la sesión inicializados.
    """
    session_attributes = {'step': 0, 'substep': 1}

    message = """Te voy a ayudar a crear un chatBot. Estos van a ser los pasos, si quieres puedes ir a uno en concreto. 
        1 - Configuración del rol IAM.
        2 - Creación del bucket
        3 - Configuración de la notificación
        4 - Creación de las funciones lambda
    Además, siempre puedes hacerme alguna pregunta acerca del paso en el que estemos. ¿Estás preparado?"""
    return build_response(message, session_attributes, 'StartTutorial')

def get_step_content(step, substep):
    """
    Obtiene el fichero contenido a través del paso y subpaso actuales desde DynamoDB.

    Parámetros:
    - step: El paso actual del tutorial.
    - substep: El subpaso actual dentro del paso.

    Retorna:
    - El nombre del fichero correspondiente al paso y subpaso desde DynamoDB, o un mensaje de error si no se encuentra el contenido.
    """
    try:
        key = f"{step}_{substep}"
        response = table.get_item(Key={'IntentName': 'tutorial', 'Question': key})
        item = response.get('Item')
        if not item:
            return "No se encontró contenido para este paso y subpaso."
        return item['Response']
    except Exception as e:
        print(f"Error al obtener contenido desde DynamoDB: {e}")
        return "Ocurrió un error al obtener el contenido del paso."


def nextStep(event):
    """
    Avanza al siguiente paso o subpaso del tutorial.

    Parámetros:
    - event: El evento desencadenado por Lex que contiene los atributos de la sesión.

    Retorna:
    - Un diccionario con el mensaje del siguiente paso o subpaso y los atributos de la sesión actualizados.
    """
    step_substep = {0: 1, 1: 2, 2: 1, 3: 1, 4: 4}
    session_attributes = event['sessionState'].get('sessionAttributes', {})
    step = int(session_attributes.get('step', 1))
    substep = int(session_attributes.get('substep', 1))
    
    if substep == step_substep.get(step, 0):
        step += 1  
        substep = 1  
    else:
        substep += 1  

    session_attributes['step'] = step
    session_attributes['substep'] = substep
    
    file_name = get_step_content(step, substep)
    
    message = read_text_file_from_s3(file_name)
    
    return build_response(message, session_attributes, 'NextStep')

def currentStep(event):
    """
    Repite el contenido del paso y subpaso actuales.

    Parámetros:
    - event: El evento desencadenado por Lex que contiene los atributos de la sesión.

    Retorna:
    - Un diccionario con el mensaje del paso y subpaso actuales y los atributos de la sesión.
    """
    session_attributes = event['sessionState'].get('sessionAttributes', {})
    step = int(session_attributes.get('step', 1))
    substep = int(session_attributes.get('substep', 1))
    
    file_name = get_step_content(step, substep)
    
    message = read_text_file_from_s3(file_name)
    
    return build_response(message, session_attributes, 'NextStep')

def goToStep(event):
    """
    Salta a un paso específico del tutorial según la solicitud del usuario.

    Parámetros:
    - event: El evento desencadenado por Lex que contiene los atributos de la sesión y el número de paso deseado.

    Retorna:
    - Un diccionario con el mensaje del paso especificado y los atributos de la sesión actualizados.
    """
    session_attributes = event['sessionState'].get('sessionAttributes', {})
    step = int(event['sessionState']['intent']['slots']['StepNumber']['value']['interpretedValue'])
    
    if step < 1 or step > 4:
        message = "Lo siento, el paso especificado no es válido. Por favor, elige un paso entre 1 y 4."
        return build_response(message, session_attributes, 'GoToStep')
    
    session_attributes['step'] = step
    session_attributes['substep'] = 1
    
    file_name = get_step_content(step, 1)
    
    message = read_text_file_from_s3(file_name)
    
    return build_response(message, session_attributes, 'NextStep')

def handle_question(event):
    """
    Maneja las preguntas específicas del usuario durante el tutorial.

    Parámetros:
    - event: El evento desencadenado por Lex que contiene los atributos de la sesión y la pregunta del usuario.

    Retorna:
    - Un diccionario con la respuesta a la pregunta del usuario y los atributos de la sesión.
    """
    intent_name = event['sessionState']['intent']['name']
    user_input = event['inputTranscript']
    session_attributes = event['sessionState'].get('sessionAttributes', {})
    
    response_message = get_most_similar_response(intent_name, user_input)
    
    return build_response(response_message, session_attributes, intent_name)

def get_most_similar_response(intent_name, user_input):
    """
    Busca la respuesta más similar a la pregunta del usuario en DynamoDB.

    Parámetros:
    - intent_name: El nombre de la intención que contiene la pregunta.
    - user_input: La pregunta realizada por el usuario.

    Retorna:
    - La respuesta más similar encontrada en DynamoDB o un mensaje de error si no se encuentra una respuesta.
    """
    try:
        response = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key('IntentName').eq(intent_name)
        )

        items = response.get('Items', [])
        if not items:
            return "Lo siento, no tengo la respuesta a esa pregunta en este momento."
        
        max_similarity = -1
        best_response = "Lo siento, no tengo la respuesta a esa pregunta en este momento."
        for item in items:
            similarity = calculate_similarity(user_input, item['Question'])
            if similarity > max_similarity:
                max_similarity = similarity
                best_response = item['Response']
        
        return best_response

    except Exception as e:
        print(f"Error al obtener la respuesta desde DynamoDB: {e}")
        return "Lo siento, ocurrió un error al procesar tu solicitud."

def calculate_similarity(user_input, stored_question):
    """
    Calcula la similitud entre la pregunta del usuario y las preguntas almacenadas.

    Parámetros:
    - user_input: La pregunta realizada por el usuario.
    - stored_question: La pregunta almacenada en DynamoDB.

    Retorna:
    - Un valor de similitud basado en la cantidad de palabras comunes entre las preguntas.
    """
    user_words = set(user_input.lower().split())
    question_words = set(stored_question.lower().split())
    common_words = user_words.intersection(question_words)
    return len(common_words) / max(len(user_words), len(question_words))

def build_response(message, session_attributes, intent_name, content_type='CustomPayload'):
    """
    Construye la respuesta en el formato esperado por Lex.

    Parámetros:
    - message: El mensaje de respuesta.
    - session_attributes: Los atributos de la sesión actuales.
    - intent_name: El nombre de la intención actual.
    - content_type: El tipo de contenido del mensaje (por defecto es 'CustomPayload').

    Retorna:
    - Un diccionario con la estructura de respuesta esperada por Lex.
    """
    response = {
        "sessionState": {
            "dialogAction": {
                "type": "Close"
            },
            "sessionAttributes": session_attributes,
            "intent": {
                'name': intent_name,
                'state': 'Fulfilled'
            }
        },
        "messages": [
            {
                "contentType": content_type,
                "content": message
            }
        ]
    }
    return response

def read_text_file_from_s3(file_name):
    """
    Lee el contenido de un archivo de texto almacenado en S3.

    Parámetros:
    - file_name: El nombre del archivo de texto en S3.

    Retorna:
    - El contenido del archivo de texto o un mensaje de error si no se puede leer el archivo.
    """
    try:
        response = s3.get_object(Bucket=bucket_name, Key=f"{folder_name}/{file_name}")
        text = response['Body'].read().decode('utf-8')
        print(text)
        return text
    except Exception as e:
        print(f"Error al leer el archivo desde S3: {e}")
        return None


