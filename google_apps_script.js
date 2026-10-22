/**
 * Google Apps Script Web App for FoodMaster Menu Outlet Drive Upload & Photo Sync.
 * 
 * Features:
 * - Dynamic Parent Folder resolution (reads folderId / parentFolderId / targetFolderId from payload,
 *   with fallback to DEFAULT_PARENT_FOLDER_ID)
 * - Hierarchical folder creation (supports nested folderPath array or single folderName)
 * - Supports batch photo uploads (files: [...]) or single file uploads (Excel C5)
 * - Sets folder and file sharing permissions (ANYONE_WITH_LINK, VIEW)
 * - Returns JSON response with folderUrl, subFolderId, and uploaded files info
 */

// Default Parent Folder ID (Target Folder Induk Owner)
var DEFAULT_PARENT_FOLDER_ID = "14EFVOjND6brFT6BKdXu5dWJBErbSMqie";

function doPost(e) {
  // LockService untuk mencegah race condition pembuatan folder ganda saat request bersamaan
  var lock = LockService.getScriptLock();
  lock.tryLock(30000); // Tunggu hingga 30 detik

  try {
    var data = JSON.parse(e.postData.contents);
    
    // 1. Tentukan Parent Folder (menggunakan targetFolderId dinamis atau fallback ke default)
    var targetFolderId = data.folderId || data.parentFolderId || data.targetFolderId || DEFAULT_PARENT_FOLDER_ID;
    var parentFolder;
    if (targetFolderId && targetFolderId.trim() !== "") {
      try {
        parentFolder = DriveApp.getFolderById(targetFolderId.trim());
      } catch (errDrive) {
        console.warn("Folder ID tidak ditemukan, menggunakan Root Folder: " + errDrive);
        parentFolder = DriveApp.getRootFolder();
      }
    } else {
      parentFolder = DriveApp.getRootFolder();
    }

    // 2. Navigasi / buat hirarki folder (mendukung nested folderPath array atau single folderName)
    var currentFolder = parentFolder;
    var folderSegments = [];
    if (Array.isArray(data.folderPath) && data.folderPath.length > 0) {
      folderSegments = data.folderPath;
    } else if (typeof data.folderPath === 'string' && data.folderPath.trim() !== "") {
      folderSegments = data.folderPath.split("/").map(function(s) { return s.trim(); }).filter(Boolean);
    } else {
      var fName = data.folderName || data.owner || data.outlet || data.outlet_name || "FoodMaster Exports";
      folderSegments = [fName.trim()];
    }

    for (var i = 0; i < folderSegments.length; i++) {
      var seg = folderSegments[i];
      if (!seg) continue;
      var folders = currentFolder.getFoldersByName(seg);
      if (folders.hasNext()) {
        currentFolder = folders.next();
      } else {
        currentFolder = currentFolder.createFolder(seg);
      }
    }
    var subFolder = currentFolder;
    try {
      subFolder.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
    } catch (eShare) {
      console.warn("Warning setting folder share permission: " + eShare);
    }

    // 3. Simpan file-file (mendukung array 'files' atau single file 'fileName' + 'fileContent')
    var uploadedFiles = [];
    var fileList = [];
    if (Array.isArray(data.files) && data.files.length > 0) {
      fileList = data.files;
    } else if (data.fileContent || data.fileBase64) {
      fileList.push({
        fileName: data.fileName || "Export.xlsx",
        fileContent: data.fileContent || data.fileBase64,
        mimeType: data.mimeType || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      });
    }

    for (var j = 0; j < fileList.length; j++) {
      var item = fileList[j];
      if (!item || (!item.fileContent && !item.fileBase64)) continue;
      var fContent = item.fileContent || item.fileBase64;
      var decoded = Utilities.base64Decode(fContent);
      var fMime = item.mimeType || "application/octet-stream";
      var fName = item.fileName || ("file_" + j);
      var blob = Utilities.newBlob(decoded, fMime, fName);

      var file = subFolder.createFile(blob);
      try {
        file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
      } catch (eFileShare) {}

      // Bersihkan file asli dari Root/Parent jika terlanjur terasosiasi di parent folder
      try {
        var root = DriveApp.getRootFolder();
        if (root.getId() !== subFolder.getId()) {
          try { root.removeFile(file); } catch (eR) {}
        }
        if (parentFolder.getId() !== subFolder.getId()) {
          try { parentFolder.removeFile(file); } catch (eP) {}
        }
      } catch (eClean) {}

      uploadedFiles.push({
        fileName: file.getName(),
        fileUrl: file.getUrl(),
        fileId: file.getId()
      });
    }

    var primaryUrl = uploadedFiles.length > 0 ? uploadedFiles[0].fileUrl : subFolder.getUrl();

    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      folderUrl: subFolder.getUrl(),
      fileUrl: primaryUrl,
      spreadsheetUrl: primaryUrl,
      subFolderName: subFolder.getName(),
      subFolderId: subFolder.getId(),
      parentFolderId: parentFolder.getId(),
      uploadedCount: uploadedFiles.length,
      files: uploadedFiles
    })).setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  } finally {
    try {
      lock.releaseLock();
    } catch (eRelease) {}
  }
}
