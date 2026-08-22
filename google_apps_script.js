/**
 * Google Apps Script Web App for FoodMaster Menu Outlet Drive Upload.
 * 
 * Features:
 * - Dynamic Parent Folder resolution (reads folderId / parentFolderId / targetFolderId from payload,
 *   with fallback to DEFAULT_PARENT_FOLDER_ID)
 * - Auto-creates Owner / Outlet subfolder inside parent folder
 * - Uploads ONLY raw .xlsx binary file into subfolder (tanpa konversi Google Sheet)
 * - Sets .xlsx file sharing permissions (ANYONE_WITH_LINK, VIEW)
 * - Removes file references from Root/Parent folder so files ONLY exist in Owner subfolder
 * - Returns JSON response with fileUrl, subFolderName, and subFolderId
 */

// Default Parent Folder ID (Target Folder Baru)
var DEFAULT_PARENT_FOLDER_ID = "14EFVOjND6brFT6BKdXu5dWJBErbSMqie";

function doPost(e) {
  // LockService untuk mencegah race condition pembuatan folder ganda saat request bersamaan
  var lock = LockService.getScriptLock();
  lock.tryLock(30000); // Tunggu hingga 30 detik

  try {
    var data = JSON.parse(e.postData.contents);
    var folderName = data.folderName || data.owner || data.outlet || data.outlet_name || "FoodMaster Exports";
    var fileName = data.fileName || "Export.xlsx";
    var fileContent = data.fileContent || data.fileBase64;
    var mimeType = data.mimeType || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
    
    // Dynamic Parent Folder ID resolution from request payload
    var targetFolderId = data.folderId || data.parentFolderId || data.targetFolderId || DEFAULT_PARENT_FOLDER_ID;

    var decoded = Utilities.base64Decode(fileContent);
    var blob = Utilities.newBlob(decoded, mimeType, fileName);
    
    // 1. Tentukan Parent Folder (menggunakan targetFolderId dinamis atau fallback ke root)
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
    
    // 2. Dapatkan atau buat subfolder (Nama Owner / Outlet) di dalam parent folder
    var targetSubFolderName = (folderName && folderName.trim() !== "") ? folderName.trim() : "FoodMaster Exports";
    var folders = parentFolder.getFoldersByName(targetSubFolderName);
    var subFolder;
    if (folders.hasNext()) {
      subFolder = folders.next();
    } else {
      subFolder = parentFolder.createFolder(targetSubFolderName);
    }
    
    // 3. Simpan file Excel asli (.xlsx) ke dalam subfolder target
    var file = subFolder.createFile(blob);
    file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
    var fileUrl = file.getUrl();

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
    
    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      fileUrl: fileUrl,
      spreadsheetUrl: fileUrl,
      subFolderName: subFolder.getName(),
      subFolderId: subFolder.getId(),
      parentFolderId: parentFolder.getId()
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
