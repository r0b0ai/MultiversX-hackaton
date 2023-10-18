import logging
import sys
import os
import datetime
from flask import Flask, request, jsonify
import qdrant_client
from datetime import datetime,timedelta, timezone
from llama_index import (
    VectorStoreIndex,
    ServiceContext,
    SimpleDirectoryReader,
)
from llama_index.storage.storage_context import StorageContext
from llama_index.vector_stores.qdrant import QdrantVectorStore
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from flask_jwt_extended import create_access_token,get_jwt,get_jwt_identity, \
                               unset_jwt_cookies, jwt_required, JWTManager

from sentry_sdk import set_user

sentry_sdk.init(
    dsn="YOUR API KEY",
    integrations=[
        FlaskIntegration(),
    ],

    # Set traces_sample_rate to 1.0 to capture 100%
    # of transactions for performance monitoring.
    # We recommend adjusting this value in production.
    traces_sample_rate=1.0,
    send_default_pii=True
)

os.environ["OPENAI_API_KEY"] = "YOUR OPEN AI API KEY"
app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = "YOUR JWT SECRET "
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=20)
app.config['PROPAGATE_EXCEPTIONS'] = True

jwt = JWTManager(app)


client = qdrant_client.QdrantClient(
    location=":memory:"
)

def initialize():
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    logging.getLogger().addHandler(logging.StreamHandler(stream=sys.stdout))

    start_time = datetime.now()

    # Get a list of all user-specific directories under "podatki-link"
    user_dirs = [d for d in os.listdir("podatki-link") if os.path.isdir(os.path.join("podatki-link", d))]

    query_engines = {}  # Dictionary to hold a query engine for each user

    for user_dir in user_dirs:
        user_specific_dir = os.path.join("podatki-link", user_dir)

        # Load documents from the user-specific directory
        documents = SimpleDirectoryReader(user_specific_dir).load_data()

        service_context = ServiceContext.from_defaults()
        vector_store = QdrantVectorStore(client=client, collection_name=f"{user_dir}_collection")
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_documents(
            documents, storage_context=storage_context, service_context=service_context
        )

        query_engine = index.as_query_engine()

        # Store the query engine in the query_engines dictionary, using the user_dir as the key
        query_engines[user_dir] = query_engine

    end_time = datetime.now()
    duration = end_time - start_time

    print(f"Initialization completed in: {duration}")

    return query_engines  # Return the dictionary of query engines


query_engines = initialize()  # Global dictionary of query engines

def handle_query(query_engine, user_query):
    start_time = datetime.now()
    
    query_instruction = (
        "Odgovori samo na podlagi konteksta ki ga dobiš, preišči celo besedilo če so kakšni sinonimi podobne besede poskušaj podati na podlagi tega odgovor, če te stranka vpraša v angleščini in iščeš po angleškem besedilu podaj odgovor v angleščini, če odgovora ni v besedilu odgovori z: 'Žal tega nevem'. Tukaj je vprašanje: "
    )
    full_query = query_instruction + user_query
    end_time = datetime.now()
    duration = end_time - start_time
    print(f"Query handling completed in: {duration}")
    return query_engine.query(full_query)  # use the passed query_engine to perform the query


@app.route('/search', methods=['GET'])
@jwt_required()
def search():
    with sentry_sdk.start_transaction(name="search website", op="endpoint"):
        user_query = request.args.get('query')

        client_ip = request.remote_addr
        user_email = get_jwt_identity()
        user_prefix = user_email.split('@')[0]  # Extract the portion of the email before the '@' symbol
        print("kajdobim tu", user_prefix)
        # Add the user's context to Sentry for enhanced error reporting
        set_user({
            "email": user_email,
            "ip_address": client_ip
        })

        if not user_query:
            return jsonify({'error': 'Query parameter missing'}), 400
        
        query_engine = query_engines.get(user_prefix)  # Get the query engine for this user
        print("kaj pa tu------",query_engine)
        if query_engine is None:
            return jsonify({'error': 'No data found for this user'}), 404  # Return error if no query engine for this user
        
        result = handle_query(query_engine, user_query)
    
        
        # Check if result is an error dictionary and return it as JSON
        if isinstance(result, dict) and 'error' in result:
            return jsonify(result), 404  # Return with a 404 Not Found status code
        
        return jsonify({'result': str(result)})



if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port="5055")
