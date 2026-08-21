class FaceGallery:
    """Compatibility adapter used only by the explicit legacy rollback path."""

    def __init__(self):
        self._entries = ()

    def reload(self):
        from src.services.face_gallery_provider import SqliteFaceGalleryProvider
        self._entries = SqliteFaceGalleryProvider().load("legacy")[0].entries
        return len(self._entries)

    def snapshot(self):
        return self._entries


face_gallery = FaceGallery()
