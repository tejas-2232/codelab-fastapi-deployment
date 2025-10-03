import os
import datetime
from fastapi import FastAPI, File, UploadFile, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from google.cloud import storage, firestore

# --- Configuration ---
# Get bucket name and firestore collection from Cloud Run env vars
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "YOUR_BUCKET_NAME_DEFAULT")
FIRESTORE_COLLECTION = os.environ.get("FIRESTORE_COLLECTION", "YOUR_FIRESTORE_DEFAULT")

# --- Initialize Google Client Libraries ---
# These client libraries will use the Application Default Credentials
# for your service account within the Cloud Run environment 
storage_client = storage.Client()
firestore_client = firestore.Client()

# --- FastAPI App ---
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serves the main upload form."""
    
    # Query Firestore for existing images to display 
    images = []
    try:
        docs = firestore_client.collection(FIRESTORE_COLLECTION).order_by(
            "uploaded_at", direction=firestore.Query.DESCENDING
        ).limit(10).stream() # Get latest 10 images
        for doc in docs:
            images.append(doc.to_dict())
    except Exception as e:
        print(f"Warning: Could not fetch images from Firestore: {e}")
        # Continue without displaying images if Firestore query fails

    return templates.TemplateResponse("index.html", {
        "request": request,
        "bucket_name": GCS_BUCKET_NAME,
        "images": images # Pass images to the template
    })

@app.post("/upload")
async def handle_upload(request: Request, file: UploadFile = File(...)):
    """Handles file upload, saves to GCS, and records in Firestore."""
    if not file:
        return {"message": "No upload file sent"}
    elif not GCS_BUCKET_NAME or GCS_BUCKET_NAME == "YOUR_BUCKET_NAME_DEFAULT":
         return {"message": "GCS Bucket Name not configured."}, 500 # Internal Server Error

    try:
        # 1. Upload to GCS
        # note: to keep the demo code short, there are no file verifications
        # for an actual real-world production app, you will want to add checks
        gcs_url = upload_to_gcs(file, GCS_BUCKET_NAME)

        # 2. Save metadata to Firestore
        save_metadata_to_firestore(file.filename, gcs_url, FIRESTORE_COLLECTION)

        # Redirect back to the main page after successful upload
        return RedirectResponse(url="/", status_code=303) # Redirect using See Other

    except Exception as e:
        print(f"Upload failed: {e}")

        return templates.TemplateResponse("index.html", {
            "request": request,
            "bucket_name": GCS_BUCKET_NAME,
            "error_message": f"Upload failed: {e}",
            "images": [] # Pass empty list on error or re-query
        }, status_code=500)

# --- Helper Functions ---
def upload_to_gcs(uploadedFile: UploadFile, bucket_name: str) -> str:
    """Uploads a file to Google Cloud Storage and returns the public URL."""
    try:
        bucket = storage_client.bucket(bucket_name)

        # Create a unique blob name (e.g., timestamp + original filename)
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
        blob_name = f"{timestamp}_{uploadedFile.filename}"
        blob = bucket.blob(blob_name)

        # Upload the file
        # Reset file pointer just in case
        uploadedFile.file.seek(0)
        blob.upload_from_file(uploadedFile.file, content_type=uploadedFile.content_type)

        print(f"File {uploadedFile.filename} uploaded to gs://{bucket_name}/{blob_name}")
        return blob.public_url # Return the public URL

    except Exception as e:
        print(f"Error uploading to GCS: {e}")
        raise  # Re-raise the exception for FastAPI to handle

def save_metadata_to_firestore(filename: str, gcs_url: str, collection_name: str):
    """Saves image metadata to Firestore."""
    try:
        doc_ref = firestore_client.collection(collection_name).document()
        doc_ref.set({
            'filename': filename,
            'gcs_url': gcs_url,
            'uploaded_at': firestore.SERVER_TIMESTAMP # Use server timestamp
        })
        print(f"Metadata saved to Firestore collection {collection_name}")
    except Exception as e:
        print(f"Error saving metadata to Firestore: {e}")
        # Consider raising the exception or handling it appropriately
        raise # Re-raise the exception