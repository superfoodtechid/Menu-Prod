/**
 * Google Apps Script Web App for FoodMaster Menu Outlet Drive Upload & Photo Sync.
 *
 * Supports:
 * - Direct CDN photo fetching via UrlFetchApp.fetchAll (parallel download inside Google's network)
 * - Base64 payload uploads for Excel workbooks or per-item fallback
 * - Hierarchical folder resolution with short-lived script lock to prevent duplicate folders
 *   without blocking concurrent photo upload batches
 */

var DEFAULT_PARENT_FOLDER_ID = "14EFVOjND6brFT6BKdXu5dWJBErbSMqie";

function resolveTargetFolder(data) {
  var lock = LockService.getScriptLock();
  var hasLock = lock.tryLock(20000);

  try {
    var targetFolderId = data.folderId || data.parentFolderId || data.targetFolderId || DEFAULT_PARENT_FOLDER_ID;
    var parentFolder;
    if (targetFolderId && String(targetFolderId).trim() !== "") {
      try {
        parentFolder = DriveApp.getFolderById(String(targetFolderId).trim());
      } catch (errDrive) {
        parentFolder = DriveApp.getRootFolder();
      }
    } else {
      parentFolder = DriveApp.getRootFolder();
    }

    var currentFolder = parentFolder;
    var folderSegments = [];
    if (Array.isArray(data.folderPath) && data.folderPath.length > 0) {
      folderSegments = data.folderPath;
    } else if (typeof data.folderPath === "string" && data.folderPath.trim() !== "") {
      folderSegments = data.folderPath.split("/").map(function(s) { return s.trim(); }).filter(Boolean);
    } else if (data.folderName || data.owner || data.outlet || data.outlet_name) {
      var fName = data.folderName || data.owner || data.outlet || data.outlet_name;
      folderSegments = [String(fName).trim()];
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
    if (folderSegments.length > 0) {
      try {
        subFolder.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
      } catch (eShare) {}
    }

    return {
      parentFolder: parentFolder,
      subFolder: subFolder
    };
  } finally {
    if (hasLock) {
      try {
        lock.releaseLock();
      } catch (eRelease) {}
    }
  }
}

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var resolved = resolveTargetFolder(data);
    var parentFolder = resolved.parentFolder;
    var subFolder = resolved.subFolder;

    var uploadedFiles = [];
    var failedFiles = [];
    var fileList = [];

    if (Array.isArray(data.files) && data.files.length > 0) {
      fileList = data.files;
    } else if (data.fileContent || data.fileBase64 || data.fileUrl || data.url) {
      fileList.push({
        fileName: data.fileName || "Export.xlsx",
        fileContent: data.fileContent || data.fileBase64,
        fileUrl: data.fileUrl || data.url,
        mimeType: data.mimeType || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      });
    }

    var urlItems = [];
    var base64Items = [];

    for (var j = 0; j < fileList.length; j++) {
      var item = fileList[j];
      if (!item) continue;
      if (item.fileContent || item.fileBase64) {
        base64Items.push({ item: item, index: j });
      } else if (item.fileUrl || item.url || item.photoUrl) {
        urlItems.push({
          item: item,
          url: String(item.fileUrl || item.url || item.photoUrl).trim(),
          index: j
        });
      }
    }

    if (urlItems.length > 0) {
      var fetchRequests = urlItems.map(function(entry) {
        return {
          url: entry.url,
          method: "get",
          muteHttpExceptions: true,
          followRedirects: true,
          headers: {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"
          }
        };
      });

      var responses = [];
      try {
        responses = UrlFetchApp.fetchAll(fetchRequests);
      } catch (fetchAllErr) {
        for (var k = 0; k < urlItems.length; k++) {
          failedFiles.push({
            fileName: urlItems[k].item.fileName || ("file_" + urlItems[k].index + ".jpg"),
            fileUrl: urlItems[k].url,
            itemId: urlItems[k].item.itemId || "",
            reason: String(fetchAllErr)
          });
        }
        responses = [];
      }

      for (var m = 0; m < responses.length; m++) {
        var entryObj = urlItems[m];
        var resp = responses[m];
        var fNameUrl = entryObj.item.fileName || ("file_" + entryObj.index + ".jpg");
        try {
          var code = resp.getResponseCode();
          if (code === 200) {
            var blobUrl = resp.getBlob();
            var bytes = blobUrl.getBytes();
            if (!bytes || bytes.length === 0) {
              failedFiles.push({
                fileName: fNameUrl,
                fileUrl: entryObj.url,
                itemId: entryObj.item.itemId || "",
                reason: "Empty response body"
              });
              continue;
            }
            blobUrl.setName(fNameUrl);
            var createdUrlFile = subFolder.createFile(blobUrl);
            uploadedFiles.push({
              fileName: createdUrlFile.getName(),
              fileUrl: createdUrlFile.getUrl(),
              fileId: createdUrlFile.getId()
            });
          } else {
            failedFiles.push({
              fileName: fNameUrl,
              fileUrl: entryObj.url,
              itemId: entryObj.item.itemId || "",
              reason: "HTTP " + code
            });
          }
        } catch (fileErr) {
          failedFiles.push({
            fileName: fNameUrl,
            fileUrl: entryObj.url,
            itemId: entryObj.item.itemId || "",
            reason: String(fileErr)
          });
        }
      }
    }

    for (var b = 0; b < base64Items.length; b++) {
      var bEntry = base64Items[b];
      var bItem = bEntry.item;
      var fNameB64 = bItem.fileName || ("file_" + bEntry.index);
      try {
        var fContent = bItem.fileContent || bItem.fileBase64;
        var decoded = Utilities.base64Decode(fContent);
        var fMime = bItem.mimeType || "application/octet-stream";
        var blobB64 = Utilities.newBlob(decoded, fMime, fNameB64);
        var createdB64File = subFolder.createFile(blobB64);
        uploadedFiles.push({
          fileName: createdB64File.getName(),
          fileUrl: createdB64File.getUrl(),
          fileId: createdB64File.getId()
        });
      } catch (b64Err) {
        failedFiles.push({
          fileName: fNameB64,
          fileUrl: bItem.fileUrl || "",
          itemId: bItem.itemId || "",
          reason: String(b64Err)
        });
      }
    }

    var primaryUrl = uploadedFiles.length > 0 ? uploadedFiles[0].fileUrl : subFolder.getUrl();

    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      mode: "direct_url_v2",
      folderUrl: subFolder.getUrl(),
      fileUrl: primaryUrl,
      spreadsheetUrl: primaryUrl,
      subFolderName: subFolder.getName(),
      subFolderId: subFolder.getId(),
      parentFolderId: parentFolder.getId(),
      uploadedCount: uploadedFiles.length,
      failedCount: failedFiles.length,
      failedFiles: failedFiles,
      files: uploadedFiles
    })).setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}
