/**
 * Google Apps Script Web App for FoodMaster Menu Outlet Drive Upload & Conversion.
 * 
 * Features:
 * - Dynamic Parent Folder resolution (reads folderId / parentFolderId / targetFolderId from payload,
 *   with fallback to DEFAULT_PARENT_FOLDER_ID)
 * - Auto-creates Owner / Outlet subfolder inside parent folder
 * - Uploads raw .xlsx binary file into subfolder
 * - Removes file references from Root/Parent folder so files ONLY exist in Owner subfolder
 * - Converts .xlsx into native Google Sheet using Drive API v2 / v3
 * - Sets Google Sheet sharing permissions (ANYONE_WITH_LINK, VIEW)
 * - Returns JSON response with fileUrl, spreadsheetUrl, subFolderName, and subFolderId
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
    var fileUrl = file.getUrl();
    var spreadsheetUrl = "";

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
    
    // 4. Konversi file Excel menjadi Google Spreadsheet menggunakan Drive API
    try {
      var sheetFile;
      if (typeof Drive.Files.insert === 'function') {
        // Drive API v2 (Default Apps Script Advanced Service)
        sheetFile = Drive.Files.insert({
          title: fileName.replace(/\.xlsx$/i, ''),
          mimeType: MimeType.GOOGLE_SHEETS,
          parents: [{id: subFolder.getId()}]
        }, blob, {convert: true});
        spreadsheetUrl = sheetFile.alternateLink;
      } else {
        // Drive API v3
        sheetFile = Drive.Files.create({
          name: fileName.replace(/\.xlsx$/i, ''),
          mimeType: MimeType.GOOGLE_SHEETS,
          parents: [subFolder.getId()]
        }, blob, {convert: true});
        spreadsheetUrl = sheetFile.webViewLink;
      }
      
      // Mengatur agar file spreadsheet dapat diakses/dilihat oleh siapa saja yang memiliki link
      if (sheetFile && sheetFile.id) {
        var sheetDriveFile = DriveApp.getFileById(sheetFile.id);
        sheetDriveFile.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);

        // Pastikan file spreadsheet hasil konversi HANYA ada di subfolder (bukan di root/parent)
        try {
          var root = DriveApp.getRootFolder();
          if (root.getId() !== subFolder.getId()) {
            try { root.removeFile(sheetDriveFile); } catch (eR2) {}
          }
          if (parentFolder.getId() !== subFolder.getId()) {
            try { parentFolder.removeFile(sheetDriveFile); } catch (eP2) {}
          }
        } catch (eClean2) {}
      }
      
    } catch (err) {
      // Fallback menggunakan URL excel asli jika Drive API Advanced Service belum diaktifkan
      spreadsheetUrl = fileUrl;
    }
    
    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      fileUrl: fileUrl,
      spreadsheetUrl: spreadsheetUrl,
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
