from pydantic import BaseModel


class UploadOut(BaseModel):
    id: str
    url: str  # /uploads/<id>, public by (unguessable) URL
    kind: str  # "image" | "video"
    content_type: str
    size: int
    filename: str
