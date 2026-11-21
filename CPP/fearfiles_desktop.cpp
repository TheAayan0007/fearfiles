// FEARFiles Desktop (C++20 + Qt6 + OpenSSL 3 + libmpv)
// Cross-compatible with fearfiles.html (FEARW3 & legacy FEARW2)
// Encrypted streaming playback, bounded document/ZIP inspection, and best-effort sensitive-memory cleanup.

#include <QApplication>
#include <QMainWindow>
#include <QStackedWidget>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QGridLayout>
#include <QPushButton>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QTreeWidget>
#include <QHeaderView>
#include <QSplitter>
#include <QPlainTextEdit>
#include <QScrollArea>
#include <QBuffer>
#include <QPixmap>
#include <QSlider>
#include <QComboBox>
#include <QProgressBar>
#include <QFileDialog>
#include <QInputDialog>
#include <QMessageBox>
#include <QDragEnterEvent>
#include <QDropEvent>
#include <QMimeData>
#include <QTimer>
#include <QFileInfo>
#include <QDir>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSet>
#include <QThread>
#include <QMutex>
#include <QKeyEvent>
#include <QFrame>
#include <QCheckBox>
#include <QOpenGLWidget>
#include <QOpenGLContext>
#include <QMetaObject>

#ifdef HAVE_QT_PDF
  #include <QPdfDocument>
  #include <QPdfView>
#endif

#ifdef HAVE_ZLIB
  #include <zlib.h>
#endif

#include <openssl/evp.h>
#include <openssl/rand.h>
#include <openssl/crypto.h>

#include <mpv/client.h>
#include <mpv/stream_cb.h>
#include <mpv/render_gl.h>

#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>
#include <algorithm>
#include <array>
#include <limits>
#include <QSaveFile>
#include <cmath>
#include <clocale>

#ifdef _WIN32
  #define NOMINMAX
  #include <windows.h>
  #include <aclapi.h>
#else
  #include <sys/mman.h>
  #include <sys/prctl.h>
  #include <sys/resource.h>
#endif

// ============================================================================
// 1. OS & RAM HARDENING UTILITIES
// ============================================================================

namespace Security {

void hardenProcess() {
#ifdef _WIN32
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    HANDLE hProc = GetCurrentProcess();
    EXPLICIT_ACCESSW ea{};
    ea.grfAccessPermissions = PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_DUP_HANDLE;
    ea.grfAccessMode = DENY_ACCESS;
    ea.grfInheritance = NO_INHERITANCE;
    ea.Trustee.TrusteeForm = TRUSTEE_IS_NAME;
    ea.Trustee.ptstrName = const_cast<LPWSTR>(L"EVERYONE");
    PACL newAcl = nullptr;
    if (SetEntriesInAclW(1, &ea, nullptr, &newAcl) == ERROR_SUCCESS && newAcl) {
        SetSecurityInfo(hProc, SE_KERNEL_OBJECT, DACL_SECURITY_INFORMATION, nullptr, nullptr, newAcl, nullptr);
        LocalFree(newAcl);
    }
#else
    prctl(PR_SET_DUMPABLE, 0);
    struct rlimit rl{0, 0};
    setrlimit(RLIMIT_CORE, &rl);
#endif
}

void protectWindowFromCapture(QWidget *w) {
#ifdef _WIN32
    if (!w) return;
    HWND hwnd = reinterpret_cast<HWND>(w->winId());
    if (hwnd) {
        SetWindowDisplayAffinity(hwnd, 0x00000011);
    }
#else
    Q_UNUSED(w);
#endif
}

inline bool lockMemory(void *ptr, size_t len) {
    if (!ptr || len == 0) return false;
#ifdef _WIN32
    return VirtualLock(ptr, len) != 0;
#else
    return mlock(ptr, len) == 0;
#endif
}

inline void unlockMemory(void *ptr, size_t len) {
    if (!ptr || len == 0) return;
#ifdef _WIN32
    VirtualUnlock(ptr, len);
#else
    munlock(ptr, len);
#endif
}

// Overwrites QLineEdit's internal buffer before clearing
inline void scrubLineEdit(QLineEdit *edit) {
    if (!edit) return;
    int len = edit->text().size();
    if (len > 0) {
        edit->setText(QString(len, QChar(' ')));
    }
    edit->clear();
}

class SecureBuffer {
public:
    SecureBuffer() = default;
    explicit SecureBuffer(size_t n) { resize(n); }
    ~SecureBuffer() { wipeAndFree(); }

    SecureBuffer(const SecureBuffer &) = delete;
    SecureBuffer &operator=(const SecureBuffer &) = delete;

    SecureBuffer(SecureBuffer &&other) noexcept
        : data_(other.data_), size_(other.size_), locked_(other.locked_) {
        other.data_ = nullptr;
        other.size_ = 0;
        other.locked_ = false;
    }

    SecureBuffer &operator=(SecureBuffer &&other) noexcept {
        if (this != &other) {
            wipeAndFree();
            data_ = other.data_;
            size_ = other.size_;
            locked_ = other.locked_;
            other.data_ = nullptr;
            other.size_ = 0;
            other.locked_ = false;
        }
        return *this;
    }

    void resize(size_t n) {
        wipeAndFree();
        if (n == 0) return;
        data_ = new uint8_t[n];
        size_ = n;
        std::memset(data_, 0, size_);
        locked_ = lockMemory(data_, size_);
    }

    void assignFromUtf8(const QByteArray &utf8) {
        resize(static_cast<size_t>(utf8.size()));
        if (size_ > 0) {
            std::memcpy(data_, utf8.constData(), size_);
        }
    }

    void wipe() {
        if (data_ && size_ > 0) OPENSSL_cleanse(data_, size_);
    }

    void wipeAndFree() {
        if (data_) {
            OPENSSL_cleanse(data_, size_);
            if (locked_) unlockMemory(data_, size_);
            delete[] data_;
            data_ = nullptr;
            size_ = 0;
            locked_ = false;
        }
    }

    uint8_t *data() { return data_; }
    const uint8_t *data() const { return data_; }
    size_t size() const { return size_; }
    bool empty() const { return size_ == 0; }

private:
    uint8_t *data_ = nullptr;
    size_t size_ = 0;
    bool locked_ = false;
};

} // namespace Security

// ============================================================================
// 2. FEARW3 / FEARW2 CRYPTO CORE (OpenSSL 3 AES-256-GCM + PBKDF2-SHA256)
// ============================================================================

namespace FearCrypto {

constexpr char MAGIC_V3[6] = {'F','E','A','R','W','3'};
constexpr char MAGIC_V2[6] = {'F','E','A','R','W','2'};
constexpr uint32_t DEFAULT_ITERS = 1200000;
constexpr uint32_t DEFAULT_CHUNK = 4 * 1024 * 1024;
constexpr size_t SALT_LEN = 16;
constexpr size_t IV_LEN = 12;
constexpr size_t TAG_LEN = 16;
constexpr size_t KEY_LEN = 32;
constexpr size_t HEADER_FIXED_LEN = 54;

using ProgressCallback = std::function<void(int percent)>;

inline void writeU32BE(uint8_t *p, uint32_t v) {
    p[0] = (v >> 24) & 0xFF; p[1] = (v >> 16) & 0xFF;
    p[2] = (v >> 8) & 0xFF;  p[3] = v & 0xFF;
}
inline uint32_t readU32BE(const uint8_t *p) {
    return (uint32_t(p[0]) << 24) | (uint32_t(p[1]) << 16) | (uint32_t(p[2]) << 8) | uint32_t(p[3]);
}
inline void writeU64BE(uint8_t *p, uint64_t v) {
    for (int i = 7; i >= 0; --i) { p[i] = v & 0xFF; v >>= 8; }
}
inline uint64_t readU64BE(const uint8_t *p) {
    uint64_t v = 0;
    for (int i = 0; i < 8; ++i) v = (v << 8) | p[i];
    return v;
}

inline void makeChunkIv(const uint8_t baseIv[IV_LEN], uint64_t index, uint8_t outIv[IV_LEN]) {
    std::memcpy(outIv, baseIv, IV_LEN);
    uint64_t x = index;
    for (int i = 11; i >= 4; --i) {
        outIv[i] ^= static_cast<uint8_t>(x & 0xFF);
        x >>= 8;
    }
}

bool isFearFile(const QString &path) {
    std::ifstream f(path.toStdString(), std::ios::binary);
    if (!f) return false;
    char magic[6]{};
    f.read(magic, 6);
    if (f.gcount() != 6) return false;
    return std::memcmp(magic, MAGIC_V3, 6) == 0 || std::memcmp(magic, MAGIC_V2, 6) == 0;
}

bool deriveKeyPBKDF2(const uint8_t *pwData, size_t pwLen, const uint8_t *salt, uint32_t iters, Security::SecureBuffer &outKey) {
    if (!pwData || pwLen == 0 || pwLen > 1024 * 1024 || iters < 600000 || iters > 5000000) return false;
    outKey.resize(KEY_LEN);
    return PKCS5_PBKDF2_HMAC(
        reinterpret_cast<const char *>(pwData), static_cast<int>(pwLen),
        salt, static_cast<int>(SALT_LEN),
        static_cast<int>(iters),
        EVP_sha256(),
        static_cast<int>(KEY_LEN),
        outKey.data()
    ) == 1;
}

bool aesGcmEncrypt(const uint8_t *key, const uint8_t *iv,
                   const uint8_t *aad, size_t aadLen,
                   const uint8_t *plain, size_t plainLen,
                   std::vector<uint8_t> &outCipherWithTag) {
    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    if (!ctx) return false;
    bool ok = false;
    int len = 0, total = 0;
    outCipherWithTag.resize(plainLen + TAG_LEN);

    do {
        if (EVP_EncryptInit_ex(ctx, EVP_aes_256_gcm(), nullptr, nullptr, nullptr) != 1) break;
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, IV_LEN, nullptr) != 1) break;
        if (EVP_EncryptInit_ex(ctx, nullptr, nullptr, key, iv) != 1) break;
        if (aad && aadLen > 0) {
            if (EVP_EncryptUpdate(ctx, nullptr, &len, aad, static_cast<int>(aadLen)) != 1) break;
        }
        if (plainLen > 0) {
            if (EVP_EncryptUpdate(ctx, outCipherWithTag.data(), &len, plain, static_cast<int>(plainLen)) != 1) break;
            total = len;
        }
        if (EVP_EncryptFinal_ex(ctx, outCipherWithTag.data() + total, &len) != 1) break;
        total += len;
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG, TAG_LEN, outCipherWithTag.data() + total) != 1) break;
        ok = true;
    } while (false);

    EVP_CIPHER_CTX_free(ctx);
    return ok;
}

bool aesGcmDecrypt(const uint8_t *key, const uint8_t *iv,
                   const uint8_t *aad, size_t aadLen,
                   const uint8_t *cipherWithTag, size_t cipherWithTagLen,
                   uint8_t *outPlain, size_t &outPlainLen) {
    if (cipherWithTagLen < TAG_LEN) return false;
    const size_t cipherLen = cipherWithTagLen - TAG_LEN;
    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    if (!ctx) return false;
    bool ok = false;
    int len = 0, total = 0;

    do {
        if (EVP_DecryptInit_ex(ctx, EVP_aes_256_gcm(), nullptr, nullptr, nullptr) != 1) break;
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, IV_LEN, nullptr) != 1) break;
        if (EVP_DecryptInit_ex(ctx, nullptr, nullptr, key, iv) != 1) break;
        if (aad && aadLen > 0) {
            if (EVP_DecryptUpdate(ctx, nullptr, &len, aad, static_cast<int>(aadLen)) != 1) break;
        }
        if (cipherLen > 0) {
            if (EVP_DecryptUpdate(ctx, outPlain, &len, cipherWithTag, static_cast<int>(cipherLen)) != 1) break;
            total = len;
        }
        uint8_t tag[TAG_LEN];
        std::memcpy(tag, cipherWithTag + cipherLen, TAG_LEN);
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG, TAG_LEN, tag) != 1) break;
        if (EVP_DecryptFinal_ex(ctx, outPlain + total, &len) != 1) break;
        total += len;
        outPlainLen = static_cast<size_t>(total);
        ok = true;
    } while (false);

    EVP_CIPHER_CTX_free(ctx);
    if (!ok) {
        if (outPlain && cipherLen) OPENSSL_cleanse(outPlain, cipherLen);
        outPlainLen = 0;
    }
    return ok;
}

struct ParsedHeader {
    bool isV3 = true;
    uint8_t fixedHeader[HEADER_FIXED_LEN]{};
    uint8_t salt[SALT_LEN]{};
    uint8_t baseIv[IV_LEN]{};
    uint32_t iterations = 0;
    uint32_t chunkSize = 0;
    uint64_t originalSize = 0;
    uint64_t dataOffset = 0;
    QString origName;
    QString origMime;
    Security::SecureBuffer key;
};

ParsedHeader openAndVerifyHeader(const QString &path, const Security::SecureBuffer &password) {
    std::ifstream f(path.toStdString(), std::ios::binary | std::ios::ate);
    if (!f) throw std::runtime_error("Cannot open file.");
    const auto endPos = f.tellg();
    if (endPos < 0) throw std::runtime_error("Cannot determine FEAR file size.");
    uint64_t fileSize = static_cast<uint64_t>(endPos);
    if (fileSize < HEADER_FIXED_LEN) throw std::runtime_error("File too short to be a FEAR file.");
    f.seekg(0);

    ParsedHeader h;
    f.read(reinterpret_cast<char *>(h.fixedHeader), HEADER_FIXED_LEN);
    if (f.gcount() != static_cast<std::streamsize>(HEADER_FIXED_LEN))
        throw std::runtime_error("Failed to read FEAR header.");

    if (std::memcmp(h.fixedHeader, MAGIC_V3, 6) == 0) h.isV3 = true;
    else if (std::memcmp(h.fixedHeader, MAGIC_V2, 6) == 0) h.isV3 = false;
    else throw std::runtime_error("Not a valid FEARW3 or FEARW2 file.");

    size_t o = 6;
    std::memcpy(h.salt, h.fixedHeader + o, SALT_LEN); o += SALT_LEN;
    std::memcpy(h.baseIv, h.fixedHeader + o, IV_LEN); o += IV_LEN;
    h.iterations = readU32BE(h.fixedHeader + o); o += 4;
    h.chunkSize = readU32BE(h.fixedHeader + o); o += 4;
    h.originalSize = readU64BE(h.fixedHeader + o); o += 8;
    uint32_t metaLen = readU32BE(h.fixedHeader + o);

    if (h.iterations < 600000 || h.iterations > 5000000 || h.chunkSize < 65536 || h.chunkSize > 16 * 1024 * 1024)
        throw std::runtime_error("Unsupported or tampered header parameters.");

    constexpr uint32_t MAX_META_CIPHER = 1024 * 1024;
    h.dataOffset = HEADER_FIXED_LEN + static_cast<uint64_t>(metaLen);
    if (metaLen < TAG_LEN || metaLen > MAX_META_CIPHER || h.dataOffset > fileSize)
        throw std::runtime_error("Corrupted FEAR header.");

    std::vector<uint8_t> metaCipher(metaLen);
    f.read(reinterpret_cast<char *>(metaCipher.data()), metaLen);
    if (static_cast<uint32_t>(f.gcount()) != metaLen)
        throw std::runtime_error("Failed to read encrypted metadata.");

    if (!deriveKeyPBKDF2(password.data(), password.size(), h.salt, h.iterations, h.key))
        throw std::runtime_error("Key derivation failed.");

    uint8_t metaIv[IV_LEN];
    makeChunkIv(h.baseIv, 0, metaIv);

    Security::SecureBuffer metaPlain(metaLen - TAG_LEN);
    size_t outLen = 0;
    const uint8_t *aad = h.isV3 ? h.fixedHeader : nullptr;
    size_t aadLen = h.isV3 ? HEADER_FIXED_LEN : 0;

    if (!aesGcmDecrypt(h.key.data(), metaIv, aad, aadLen, metaCipher.data(), metaCipher.size(), metaPlain.data(), outLen))
        throw std::runtime_error("Wrong password, or file header was tampered with.");

    QByteArray metadataJson(reinterpret_cast<const char *>(metaPlain.data()), static_cast<int>(outLen));
    QJsonDocument doc = QJsonDocument::fromJson(metadataJson);
    OPENSSL_cleanse(metadataJson.data(), static_cast<size_t>(metadataJson.size()));
    metaPlain.wipe();
    if (!doc.isObject()) throw std::runtime_error("Corrupted metadata JSON.");
    QJsonObject obj = doc.object();
    h.origName = obj.value("name").toString();
    h.origMime = obj.value("type").toString("application/octet-stream");
    if (h.origName.isEmpty() || h.origName.size() > 4096 || h.origName.contains(QChar::Null))
        throw std::runtime_error("Missing or invalid filename in metadata.");
    if (h.originalSize > static_cast<uint64_t>(std::numeric_limits<int64_t>::max()))
        throw std::runtime_error("File is too large for this platform.");
    const uint64_t chunks = std::max<uint64_t>(1, h.originalSize / h.chunkSize + (h.originalSize % h.chunkSize != 0));
    if (h.originalSize > std::numeric_limits<uint64_t>::max() - h.dataOffset)
        throw std::runtime_error("Invalid FEAR file size arithmetic.");
    const uint64_t baseSize = h.dataOffset + h.originalSize;
    if (chunks > (std::numeric_limits<uint64_t>::max() - baseSize) / (4 + TAG_LEN))
        throw std::runtime_error("Invalid FEAR file size arithmetic.");
    const uint64_t expectedSize = h.dataOffset + h.originalSize + chunks * (4 + TAG_LEN);
    if (expectedSize != fileSize)
        throw std::runtime_error("FEAR file length does not match authenticated header.");
    return h;
}

void buildChunkAad(const ParsedHeader &h, uint64_t chunkIdx, uint32_t plainLen, bool isFinal, std::vector<uint8_t> &aad) {
    if (h.isV3) {
        aad.resize(HEADER_FIXED_LEN + 8 + 4 + 1);
        std::memcpy(aad.data(), h.fixedHeader, HEADER_FIXED_LEN);
        writeU64BE(aad.data() + HEADER_FIXED_LEN, chunkIdx);
        writeU32BE(aad.data() + HEADER_FIXED_LEN + 8, plainLen);
        aad[HEADER_FIXED_LEN + 12] = isFinal ? 1 : 0;
    } else {
        aad.resize(6 + 8 + 4);
        std::memcpy(aad.data(), MAGIC_V2, 6);
        writeU64BE(aad.data() + 6, chunkIdx);
        writeU32BE(aad.data() + 14, plainLen);
    }
}

QString makeUniquePath(const QString &dirPath, const QString &fileName) {
    QDir dir(dirPath);
    QString candidate = dir.filePath(fileName);
    if (!QFileInfo::exists(candidate)) return candidate;

    QFileInfo fi(fileName);
    QString base = fi.completeBaseName();
    QString ext = fi.suffix();
    for (int n = 1; n < 10000; ++n) {
        QString nextName = ext.isEmpty()
            ? QString("%1 (%2)").arg(base).arg(n)
            : QString("%1 (%2).%3").arg(base).arg(n).arg(ext);
        candidate = dir.filePath(nextName);
        if (!QFileInfo::exists(candidate)) return candidate;
    }
    throw std::runtime_error("Too many duplicate filenames in output directory.");
}

void encryptFile(const QString &inPath, const QString &outPath, const Security::SecureBuffer &password,
                 const ProgressCallback &onProgress = nullptr) {
    std::ifstream in(inPath.toStdString(), std::ios::binary | std::ios::ate);
    if (!in) throw std::runtime_error("Cannot open input file.");
    const auto inputEnd = in.tellg();
    if (inputEnd < 0) throw std::runtime_error("Cannot determine input file size.");
    uint64_t fileSize = static_cast<uint64_t>(inputEnd);
    in.seekg(0);

    uint8_t salt[SALT_LEN], baseIv[IV_LEN];
    if (RAND_bytes(salt, SALT_LEN) != 1 || RAND_bytes(baseIv, IV_LEN) != 1)
        throw std::runtime_error("CSPRNG failure.");

    Security::SecureBuffer key;
    if (!deriveKeyPBKDF2(password.data(), password.size(), salt, DEFAULT_ITERS, key))
        throw std::runtime_error("PBKDF2 failed.");

    QJsonObject metaObj;
    metaObj["name"] = QFileInfo(inPath).fileName();
    metaObj["type"] = "application/octet-stream";
    QByteArray metaJson = QJsonDocument(metaObj).toJson(QJsonDocument::Compact);

    uint8_t fixedHeader[HEADER_FIXED_LEN];
    std::memcpy(fixedHeader, MAGIC_V3, 6);
    std::memcpy(fixedHeader + 6, salt, SALT_LEN);
    std::memcpy(fixedHeader + 22, baseIv, IV_LEN);
    writeU32BE(fixedHeader + 34, DEFAULT_ITERS);
    writeU32BE(fixedHeader + 38, DEFAULT_CHUNK);
    writeU64BE(fixedHeader + 42, fileSize);
    writeU32BE(fixedHeader + 50, static_cast<uint32_t>(metaJson.size() + TAG_LEN));

    uint8_t metaIv[IV_LEN];
    makeChunkIv(baseIv, 0, metaIv);
    std::vector<uint8_t> metaCipher;
    if (!aesGcmEncrypt(key.data(), metaIv, fixedHeader, HEADER_FIXED_LEN,
                       reinterpret_cast<const uint8_t *>(metaJson.constData()), metaJson.size(), metaCipher))
        throw std::runtime_error("Metadata encryption failed.");
    if (!metaJson.isEmpty()) OPENSSL_cleanse(metaJson.data(), static_cast<size_t>(metaJson.size()));

    std::ofstream out(outPath.toStdString(), std::ios::binary | std::ios::trunc);
    if (!out) throw std::runtime_error("Cannot create output file.");

    auto cleanupOnFail = [&]() {
        out.close();
        std::error_code ec;
        std::filesystem::remove(outPath.toStdString(), ec);
    };

    try {
        out.write(reinterpret_cast<const char *>(fixedHeader), HEADER_FIXED_LEN);
        out.write(reinterpret_cast<const char *>(metaCipher.data()), static_cast<std::streamsize>(metaCipher.size()));
        if (!out) throw std::runtime_error("Disk write failed while writing header.");

        uint64_t totalChunks = std::max<uint64_t>(1, fileSize / DEFAULT_CHUNK + (fileSize % DEFAULT_CHUNK != 0));
        Security::SecureBuffer plainBuf(DEFAULT_CHUNK);
        std::vector<uint8_t> cipherBuf, aad;

        for (uint64_t idx = 0; idx < totalChunks; ++idx) {
            uint64_t start = idx * DEFAULT_CHUNK;
            uint32_t plainLen = static_cast<uint32_t>(std::min<uint64_t>(DEFAULT_CHUNK, fileSize - start));
            if (plainLen > 0) {
                in.read(reinterpret_cast<char *>(plainBuf.data()), plainLen);
                if (static_cast<uint32_t>(in.gcount()) != plainLen)
                    throw std::runtime_error("Disk read error or unexpected EOF on input file.");
            }

            uint8_t iv[IV_LEN];
            makeChunkIv(baseIv, idx + 1, iv);
            bool isFinal = (idx == totalChunks - 1);

            aad.resize(HEADER_FIXED_LEN + 13);
            std::memcpy(aad.data(), fixedHeader, HEADER_FIXED_LEN);
            writeU64BE(aad.data() + HEADER_FIXED_LEN, idx);
            writeU32BE(aad.data() + HEADER_FIXED_LEN + 8, plainLen);
            aad[HEADER_FIXED_LEN + 12] = isFinal ? 1 : 0;

            if (!aesGcmEncrypt(key.data(), iv, aad.data(), aad.size(), plainBuf.data(), plainLen, cipherBuf))
                throw std::runtime_error("Chunk encryption failed.");
            plainBuf.wipe();

            uint8_t lenBytes[4];
            writeU32BE(lenBytes, plainLen);
            out.write(reinterpret_cast<const char *>(lenBytes), 4);
            out.write(reinterpret_cast<const char *>(cipherBuf.data()), static_cast<std::streamsize>(cipherBuf.size()));
            if (!out) throw std::runtime_error("Disk write failed (out of space or I/O error).");

            if (onProgress) {
                onProgress(static_cast<int>(((idx + 1) * 100) / totalChunks));
            }
        }
        out.flush();
        if (!out) throw std::runtime_error("Failed to flush encrypted file to disk.");
    } catch (...) {
        cleanupOnFail();
        throw;
    }
}

void decryptFileToDisk(const QString &inPath, const QString &outDir, const Security::SecureBuffer &password,
                       QString &outSavedName, const ProgressCallback &onProgress = nullptr) {
    ParsedHeader h = openAndVerifyHeader(inPath, password);
    QString normalizedName = h.origName;
    normalizedName.replace('\\', '/');
    QString safeName = QFileInfo(normalizedName).fileName();
    if (safeName.isEmpty() || safeName == "." || safeName == ".." || safeName.contains(QChar::Null)) throw std::runtime_error("Invalid filename in metadata.");

    QString outPath = makeUniquePath(outDir, safeName);
    outSavedName = QFileInfo(outPath).fileName();

    std::ifstream in(inPath.toStdString(), std::ios::binary);
    if (!in) throw std::runtime_error("Cannot open encrypted file.");
    in.seekg(static_cast<std::streamoff>(h.dataOffset));

    std::ofstream out(outPath.toStdString(), std::ios::binary | std::ios::trunc);
    if (!out) throw std::runtime_error("Cannot write output file.");

    auto cleanupOnFail = [&]() {
        out.close();
        std::error_code ec;
        std::filesystem::remove(outPath.toStdString(), ec);
    };

    try {
        uint64_t totalChunks = std::max<uint64_t>(1, h.originalSize / h.chunkSize + (h.originalSize % h.chunkSize != 0));
        Security::SecureBuffer plainBuf(h.chunkSize);
        std::vector<uint8_t> cipherBuf, aad;

        for (uint64_t idx = 0; idx < totalChunks; ++idx) {
            uint8_t lenBytes[4];
            in.read(reinterpret_cast<char *>(lenBytes), 4);
            if (in.gcount() != 4) throw std::runtime_error("Truncated encrypted file (missing chunk length).");

            uint32_t plainLen = readU32BE(lenBytes);
            const uint64_t chunkStart = idx * static_cast<uint64_t>(h.chunkSize);
            const uint32_t expectedLen = (h.originalSize == 0) ? 0 :
                static_cast<uint32_t>(std::min<uint64_t>(h.chunkSize, h.originalSize - chunkStart));
            if (plainLen != expectedLen)
                throw std::runtime_error("Invalid chunk length or chunk ordering.");

            cipherBuf.resize(plainLen + TAG_LEN);
            in.read(reinterpret_cast<char *>(cipherBuf.data()), static_cast<std::streamsize>(cipherBuf.size()));
            if (static_cast<size_t>(in.gcount()) != cipherBuf.size())
                throw std::runtime_error("Truncated encrypted file (incomplete chunk).");

            uint8_t iv[IV_LEN];
            makeChunkIv(h.baseIv, idx + 1, iv);
            buildChunkAad(h, idx, plainLen, idx == totalChunks - 1, aad);

            size_t outLen = 0;
            if (!aesGcmDecrypt(h.key.data(), iv, aad.data(), aad.size(), cipherBuf.data(), cipherBuf.size(), plainBuf.data(), outLen) || outLen != plainLen)
                throw std::runtime_error("Chunk authentication failed (file corrupted or tampered).");

            if (plainLen > 0) {
                out.write(reinterpret_cast<const char *>(plainBuf.data()), plainLen);
                if (!out) throw std::runtime_error("Disk write failed while decrypting.");
            }
            plainBuf.wipe();

            if (onProgress) {
                onProgress(static_cast<int>(((idx + 1) * 100) / totalChunks));
            }
        }

        // Verify no trailing garbage was appended after the authenticated final chunk
        if (in.peek() != std::ifstream::traits_type::eof()) {
            throw std::runtime_error("Unexpected trailing data detected after final authenticated chunk.");
        }

        out.flush();
        if (!out) throw std::runtime_error("Failed to flush decrypted file to disk.");
    } catch (...) {
        cleanupOnFail();
        throw;
    }
}

bool isSupportedMedia(const QString &filename) {
    static const QSet<QString> mediaExts = {
        "mkv","mp4","m4v","webm","mov","avi","ts","m2ts","flv","wmv","ogv","3gp",
        "mp3","flac","alac","m4a","wav","ogg","opus","aac","wma","aiff","ape","wv"
    };
    return mediaExts.contains(QFileInfo(filename).suffix().toLower());
}

} // namespace FearCrypto

// ============================================================================
// 3. ZERO-DISK RANDOM-ACCESS STREAM (Used by libmpv & Lazy ZIP Inspector)
// ============================================================================

struct FearMediaStream {
    std::ifstream file;
    FearCrypto::ParsedHeader h;
    uint64_t pos = 0;
    uint64_t totalChunks = 0;

    int64_t cachedChunkIdx = -1;
    size_t cachedChunkLen = 0;
    Security::SecureBuffer chunkPlain;
    std::vector<uint8_t> chunkCipher;
    std::vector<uint8_t> aad;

    bool loadChunk(uint64_t idx) {
        if (static_cast<int64_t>(idx) == cachedChunkIdx) return true;
        if (idx >= totalChunks) return false;

        chunkPlain.wipe();
        cachedChunkIdx = -1;

        const uint64_t recordSize = 4ULL + h.chunkSize + FearCrypto::TAG_LEN;
        if (idx > (std::numeric_limits<uint64_t>::max() - h.dataOffset) / recordSize) return false;
        const uint64_t fileOff = h.dataOffset + idx * recordSize;
        file.clear();
        file.seekg(static_cast<std::streamoff>(fileOff), std::ios::beg);
        if (!file) return false;

        uint8_t lenBytes[4];
        file.read(reinterpret_cast<char *>(lenBytes), 4);
        if (file.gcount() != 4) return false;
        uint32_t plainLen = FearCrypto::readU32BE(lenBytes);
        const uint64_t chunkStart = idx * static_cast<uint64_t>(h.chunkSize);
        const uint32_t expectedLen = (h.originalSize == 0) ? 0 :
            static_cast<uint32_t>(std::min<uint64_t>(h.chunkSize, h.originalSize - chunkStart));
        if (plainLen != expectedLen) return false;

        chunkCipher.resize(plainLen + FearCrypto::TAG_LEN);
        file.read(reinterpret_cast<char *>(chunkCipher.data()), static_cast<std::streamsize>(chunkCipher.size()));
        if (static_cast<size_t>(file.gcount()) != chunkCipher.size()) return false;

        uint8_t iv[FearCrypto::IV_LEN];
        FearCrypto::makeChunkIv(h.baseIv, idx + 1, iv);
        FearCrypto::buildChunkAad(h, idx, plainLen, idx == totalChunks - 1, aad);

        if (chunkPlain.size() < h.chunkSize) chunkPlain.resize(h.chunkSize);
        size_t outLen = 0;
        if (!FearCrypto::aesGcmDecrypt(h.key.data(), iv, aad.data(), aad.size(),
                                       chunkCipher.data(), chunkCipher.size(),
                                       chunkPlain.data(), outLen) || outLen != plainLen) {
            chunkPlain.wipe();
            return false;
        }
        cachedChunkIdx = static_cast<int64_t>(idx);
        cachedChunkLen = outLen;
        return true;
    }

    bool readAt(uint64_t offset, uint8_t *dst, size_t len) {
        if (offset > h.originalSize || static_cast<uint64_t>(len) > h.originalSize - offset) return false;
        size_t copied = 0;
        while (copied < len) {
            uint64_t cur = offset + copied;
            uint64_t chunkIdx = cur / h.chunkSize;
            size_t chunkOff = static_cast<size_t>(cur % h.chunkSize);
            if (!loadChunk(chunkIdx)) return false;
            if (chunkOff >= cachedChunkLen) return false;
            size_t avail = cachedChunkLen - chunkOff;
            size_t step = std::min(len - copied, avail);
            std::memcpy(dst + copied, chunkPlain.data() + chunkOff, step);
            copied += step;
        }
        return true;
    }

    ~FearMediaStream() {
        chunkPlain.wipeAndFree();
        h.key.wipeAndFree();
    }
};

struct PendingStreamStore {
    std::mutex mtx;
    std::unique_ptr<FearMediaStream> pending;
};

static int64_t mpv_read_fn(void *cookie, char *buf, uint64_t nbytes) {
    auto *s = static_cast<FearMediaStream *>(cookie);
    if (s->pos >= s->h.originalSize) return 0;
    uint64_t toRead = std::min<uint64_t>(nbytes, s->h.originalSize - s->pos);
    uint64_t copied = 0;
    while (copied < toRead) {
        uint64_t chunkIdx = s->pos / s->h.chunkSize;
        size_t chunkOff = static_cast<size_t>(s->pos % s->h.chunkSize);
        if (!s->loadChunk(chunkIdx)) return -1;
        if (chunkOff >= s->cachedChunkLen) return -1;
        size_t avail = s->cachedChunkLen - chunkOff;
        size_t step = static_cast<size_t>(std::min<uint64_t>(toRead - copied, avail));
        std::memcpy(buf + copied, s->chunkPlain.data() + chunkOff, step);
        s->pos += step;
        copied += step;
    }
    return static_cast<int64_t>(copied);
}

static int64_t mpv_seek_fn(void *cookie, int64_t offset) {
    auto *s = static_cast<FearMediaStream *>(cookie);
    if (offset < 0 || static_cast<uint64_t>(offset) > s->h.originalSize) return MPV_ERROR_GENERIC;
    s->pos = static_cast<uint64_t>(offset);
    return offset;
}

static int64_t mpv_size_fn(void *cookie) {
    auto *s = static_cast<FearMediaStream *>(cookie);
    return static_cast<int64_t>(s->h.originalSize);
}

static void mpv_close_fn(void *cookie) {
    auto *s = static_cast<FearMediaStream *>(cookie);
    delete s;
}

static int mpv_open_fn(void *user_data, char * /*uri*/, mpv_stream_cb_info *info) {
    auto *store = static_cast<PendingStreamStore *>(user_data);
    std::lock_guard<std::mutex> lock(store->mtx);
    if (!store->pending) return MPV_ERROR_LOADING_FAILED;
    info->cookie = store->pending.release();
    info->read_fn = mpv_read_fn;
    info->seek_fn = mpv_seek_fn;
    info->size_fn = mpv_size_fn;
    info->close_fn = mpv_close_fn;
    return 0;
}

// ============================================================================
// 4. IN-WINDOW LIBMPV OPENGL WIDGET (Never spawns a separate window!)
// ============================================================================

class MpvGlWidget : public QOpenGLWidget {
    Q_OBJECT
public:
    explicit MpvGlWidget(mpv_handle *mpv, QWidget *parent = nullptr)
        : QOpenGLWidget(parent), mpv_(mpv) {}

    ~MpvGlWidget() override {
        makeCurrent();
        if (mpvGl_) {
            mpv_render_context_free(mpvGl_);
            mpvGl_ = nullptr;
        }
        doneCurrent();
    }

public slots:
    void maybeUpdate() {
        if (window()->isMinimized()) {
            makeCurrent();
            paintGL();
            context()->swapBuffers(context()->surface());
            doneCurrent();
        } else {
            update();
        }
    }

protected:
    void initializeGL() override {
        mpv_opengl_init_params glInit{ getProcAddress, nullptr };
        mpv_render_param params[] = {
            { MPV_RENDER_PARAM_API_TYPE, const_cast<char *>(MPV_RENDER_API_TYPE_OPENGL) },
            { MPV_RENDER_PARAM_OPENGL_INIT_PARAMS, &glInit },
            { MPV_RENDER_PARAM_INVALID, nullptr }
        };
        if (mpv_render_context_create(&mpvGl_, mpv_, params) < 0)
            throw std::runtime_error("Failed to initialize libmpv OpenGL render context.");
        mpv_render_context_set_update_callback(mpvGl_, onMpvUpdate, this);
    }

    void paintGL() override {
        if (!mpvGl_) return;
        const qreal dpr = devicePixelRatioF();
        mpv_opengl_fbo fbo{
            static_cast<int>(defaultFramebufferObject()),
            static_cast<int>(width() * dpr),
            static_cast<int>(height() * dpr),
            0
        };
        int flipY = 1;
        mpv_render_param params[] = {
            { MPV_RENDER_PARAM_OPENGL_FBO, &fbo },
            { MPV_RENDER_PARAM_FLIP_Y, &flipY },
            { MPV_RENDER_PARAM_INVALID, nullptr }
        };
        mpv_render_context_render(mpvGl_, params);
    }

private:
    static void *getProcAddress(void *, const char *name) {
        QOpenGLContext *ctx = QOpenGLContext::currentContext();
        return ctx ? reinterpret_cast<void *>(ctx->getProcAddress(QByteArray(name))) : nullptr;
    }

    static void onMpvUpdate(void *ctx) {
        auto *self = static_cast<MpvGlWidget *>(ctx);
        QMetaObject::invokeMethod(self, "maybeUpdate", Qt::QueuedConnection);
    }

    mpv_handle *mpv_ = nullptr;
    mpv_render_context *mpvGl_ = nullptr;
};

// ============================================================================
// 5. VLC-STYLE FEARFILES PLAYER PAGE (Embedded In-Window)
// ============================================================================

class FearPlayerPage : public QWidget {
    Q_OBJECT
public:
    explicit FearPlayerPage(QWidget *parent = nullptr) : QWidget(parent) {
        setAcceptDrops(true);
        setStyleSheet("background:#0D0F0E; color:#FFFFFF;");

        initMpv();

        auto *root = new QVBoxLayout(this);
        root->setContentsMargins(0, 0, 0, 0);
        root->setSpacing(0);

        videoCanvas_ = new MpvGlWidget(mpv_, this);
        videoCanvas_->setMinimumHeight(360);

        overlayHint_ = new QLabel(
            "Drop any .fearfiles media here (MKV, MP4, FLAC, ALAC, MP3...)\n"
            "Authenticated encrypted streaming · Best-effort sensitive RAM cleanup",
            videoCanvas_
        );
        overlayHint_->setAlignment(Qt::AlignCenter);
        overlayHint_->setStyleSheet("color:#9AA39E; font-size:15px; background:transparent;");
        auto *canvasLay = new QVBoxLayout(videoCanvas_);
        canvasLay->addWidget(overlayHint_);

        root->addWidget(videoCanvas_, 1);

        auto *ctrlBar = new QWidget(this);
        ctrlBar->setStyleSheet("background:#151917; border-top:1px solid #262C29;");
        auto *ctrlLay = new QVBoxLayout(ctrlBar);
        ctrlLay->setContentsMargins(14, 8, 14, 10);
        ctrlLay->setSpacing(6);

        auto *timeRow = new QHBoxLayout();
        timeCur_ = new QLabel("00:00");
        timeTot_ = new QLabel("00:00");
        timeline_ = new QSlider(Qt::Horizontal);
        timeline_->setRange(0, 1000);
        timeRow->addWidget(timeCur_);
        timeRow->addWidget(timeline_, 1);
        timeRow->addWidget(timeTot_);
        ctrlLay->addLayout(timeRow);

        auto *btnRow = new QHBoxLayout();
        playBtn_ = new QPushButton("Play / Pause");
        stopBtn_ = new QPushButton("Stop & Wipe RAM");
        openBtn_ = new QPushButton("Open .fearfiles");
        fsBtn_ = new QPushButton("Fullscreen");

        audioBox_ = new QComboBox();
        audioBox_->addItem("Audio: Auto", "auto");
        subBox_ = new QComboBox();
        subBox_->addItem("Subtitles: Off", "no");

        volSlider_ = new QSlider(Qt::Horizontal);
        volSlider_->setRange(0, 100);
        volSlider_->setValue(80);
        volSlider_->setFixedWidth(90);

        for (auto *b : {playBtn_, stopBtn_, openBtn_, fsBtn_}) {
            b->setStyleSheet("QPushButton{background:#1F5C43; color:#fff; border:none; border-radius:6px; padding:6px 12px; font-weight:600;} QPushButton:hover{background:#174934;}");
        }
        stopBtn_->setStyleSheet("QPushButton{background:#B3261E; color:#fff; border:none; border-radius:6px; padding:6px 12px; font-weight:600;}");

        btnRow->addWidget(playBtn_);
        btnRow->addWidget(stopBtn_);
        btnRow->addWidget(openBtn_);
        btnRow->addSpacing(10);
        btnRow->addWidget(new QLabel("Audio:"));
        btnRow->addWidget(audioBox_);
        btnRow->addWidget(new QLabel("Sub:"));
        btnRow->addWidget(subBox_);
        btnRow->addStretch();
        btnRow->addWidget(new QLabel("Vol:"));
        btnRow->addWidget(volSlider_);
        btnRow->addWidget(fsBtn_);
        ctrlLay->addLayout(btnRow);

        root->addWidget(ctrlBar);

        connect(openBtn_, &QPushButton::clicked, this, [this]() {
            QString p = QFileDialog::getOpenFileName(this, "Open Encrypted FEAR Media", "", "FEAR Files (*.fearfiles);;All Files (*)");
            if (!p.isEmpty()) unlockAndPlay(p);
        });
        connect(playBtn_, &QPushButton::clicked, this, &FearPlayerPage::togglePause);
        connect(stopBtn_, &QPushButton::clicked, this, &FearPlayerPage::stopAndWipe);
        connect(fsBtn_, &QPushButton::clicked, this, [this]() { emit toggleFullscreenRequested(); });

        connect(timeline_, &QSlider::sliderPressed, this, [this]() { seeking_ = true; });
        connect(timeline_, &QSlider::sliderReleased, this, [this]() {
            seeking_ = false;
            if (mpv_ && duration_ > 0.0) {
                double target = (timeline_->value() / 1000.0) * duration_;
                mpv_set_property(mpv_, "time-pos", MPV_FORMAT_DOUBLE, &target);
            }
        });
        connect(volSlider_, &QSlider::valueChanged, this, [this](int v) {
            if (mpv_) { double dv = v; mpv_set_property(mpv_, "volume", MPV_FORMAT_DOUBLE, &dv); }
        });
        connect(audioBox_, QOverload<int>::of(&QComboBox::activated), this, [this](int idx) {
            if (!mpv_) return;
            QByteArray val = audioBox_->itemData(idx).toString().toUtf8();
            mpv_set_property_string(mpv_, "aid", val.constData());
        });
        connect(subBox_, QOverload<int>::of(&QComboBox::activated), this, [this](int idx) {
            if (!mpv_) return;
            QByteArray val = subBox_->itemData(idx).toString().toUtf8();
            mpv_set_property_string(mpv_, "sid", val.constData());
        });

        auto *evTimer = new QTimer(this);
        connect(evTimer, &QTimer::timeout, this, &FearPlayerPage::pollMpvEvents);
        evTimer->start(40);
    }

    ~FearPlayerPage() override {
        stopAndWipe();
        delete videoCanvas_;
        videoCanvas_ = nullptr;
        if (mpv_) mpv_terminate_destroy(mpv_);
    }

    void unlockAndPlay(const QString &fearPath) {
        bool ok = false;
        QString qpw = QInputDialog::getText(
            this,
            "Unlock FEAR Media",
            "Enter password to inspect metadata & stream:\n" + QFileInfo(fearPath).fileName(),
            QLineEdit::Password, "", &ok
        );
        if (!ok || qpw.isEmpty()) return;

        Security::SecureBuffer pwBuf;
        QByteArray utf8 = qpw.toUtf8();
        pwBuf.assignFromUtf8(utf8);
        OPENSSL_cleanse(utf8.data(), static_cast<size_t>(utf8.size()));
        qpw.fill(QChar('\0'));

        try {
            FearCrypto::ParsedHeader h = FearCrypto::openAndVerifyHeader(fearPath, pwBuf);
            pwBuf.wipeAndFree();

            if (!FearCrypto::isSupportedMedia(h.origName)) {
                h.key.wipeAndFree();
                QMessageBox::information(
                    this, "Not a Media File",
                    "Authenticated metadata shows:\n\nName: " + h.origName +
                    "\nSize: " + QString::number(h.originalSize) + " bytes\n\n"
                    "This is not a supported audio/video format. Use the Read or Decrypt tab instead."
                );
                return;
            }

            stopAndWipe();
            auto stream = std::make_unique<FearMediaStream>();
            stream->file.open(fearPath.toStdString(), std::ios::binary);
            if (!stream->file) throw std::runtime_error("Cannot open file for streaming.");
            stream->totalChunks = std::max<uint64_t>(1, h.originalSize / h.chunkSize + (h.originalSize % h.chunkSize != 0));
            stream->h = std::move(h);

            {
                std::lock_guard<std::mutex> lock(streamStore_.mtx);
                streamStore_.pending = std::move(stream);
            }

            overlayHint_->hide();
            const char *cmd[] = {"loadfile", "fear://active_stream", nullptr};
            mpv_command_async(mpv_, 0, cmd);
        } catch (const std::exception &ex) {
            pwBuf.wipeAndFree();
            QMessageBox::critical(this, "Unlock Failed", ex.what());
        }
    }

    void togglePause() {
        if (!mpv_) return;
        int flag = 0;
        mpv_get_property(mpv_, "pause", MPV_FORMAT_FLAG, &flag);
        flag = !flag;
        mpv_set_property(mpv_, "pause", MPV_FORMAT_FLAG, &flag);
    }

    void stopAndWipe() {
        if (mpv_) {
            const char *cmd[] = {"stop", nullptr};
            mpv_command(mpv_, cmd);
        }
        {
            std::lock_guard<std::mutex> lock(streamStore_.mtx);
            streamStore_.pending.reset();
        }
        overlayHint_->show();
        timeline_->setValue(0);
        timeCur_->setText("00:00");
        timeTot_->setText("00:00");
        duration_ = 0.0;
    }

signals:
    void toggleFullscreenRequested();

protected:
    void dragEnterEvent(QDragEnterEvent *e) override {
        if (e->mimeData()->hasUrls()) e->acceptProposedAction();
    }
    void dropEvent(QDropEvent *e) override {
        auto urls = e->mimeData()->urls();
        if (!urls.isEmpty()) unlockAndPlay(urls.first().toLocalFile());
    }

private:
    void initMpv() {
        mpv_ = mpv_create();
        if (!mpv_) throw std::runtime_error("Failed to create libmpv context.");

        mpv_set_option_string(mpv_, "vo", "libmpv");
        mpv_set_option_string(mpv_, "config", "no");
        mpv_set_option_string(mpv_, "ytdl", "no");
        mpv_set_option_string(mpv_, "save-position-on-quit", "no");
        mpv_set_option_string(mpv_, "cache", "no");
        mpv_set_option_string(mpv_, "demuxer-max-bytes", "16MiB");
        mpv_set_option_string(mpv_, "demuxer-max-back-bytes", "4MiB");
        mpv_set_option_string(mpv_, "hwdec", "auto-safe");
        mpv_set_option_string(mpv_, "keep-open", "no");

        if (mpv_initialize(mpv_) < 0) throw std::runtime_error("Failed to initialize libmpv.");

        mpv_stream_cb_add_ro(mpv_, "fear", &streamStore_, mpv_open_fn);

        mpv_observe_property(mpv_, 1, "time-pos", MPV_FORMAT_DOUBLE);
        mpv_observe_property(mpv_, 2, "duration", MPV_FORMAT_DOUBLE);
        mpv_observe_property(mpv_, 3, "track-list", MPV_FORMAT_NODE);
    }

    static QString fmtTime(double sec) {
        if (sec < 0 || !std::isfinite(sec)) return "00:00";
        int s = static_cast<int>(sec);
        int h = s / 3600, m = (s % 3600) / 60, r = s % 60;
        return h > 0 ? QString("%1:%2:%3").arg(h).arg(m, 2, 10, QChar('0')).arg(r, 2, 10, QChar('0'))
                     : QString("%1:%2").arg(m, 2, 10, QChar('0')).arg(r, 2, 10, QChar('0'));
    }

    void refreshTracks(const mpv_node *node) {
        audioBox_->clear();
        subBox_->clear();
        subBox_->addItem("Subtitles: Off", "no");
        if (!node || node->format != MPV_FORMAT_NODE_ARRAY) return;

        for (int i = 0; i < node->u.list->num; ++i) {
            const mpv_node &item = node->u.list->values[i];
            if (item.format != MPV_FORMAT_NODE_MAP) continue;
            QString type, lang, title;
            int64_t id = -1;
            for (int k = 0; k < item.u.list->num; ++k) {
                const char *key = item.u.list->keys[k];
                const mpv_node &v = item.u.list->values[k];
                if (std::strcmp(key, "type") == 0 && v.format == MPV_FORMAT_STRING) type = v.u.string;
                else if (std::strcmp(key, "lang") == 0 && v.format == MPV_FORMAT_STRING) lang = v.u.string;
                else if (std::strcmp(key, "title") == 0 && v.format == MPV_FORMAT_STRING) title = v.u.string;
                else if (std::strcmp(key, "id") == 0 && v.format == MPV_FORMAT_INT64) id = v.u.int64;
            }
            if (id < 0) continue;
            QString label = QString("#%1").arg(id);
            if (!lang.isEmpty()) label += " [" + lang + "]";
            if (!title.isEmpty()) label += " " + title;
            if (type == "audio") audioBox_->addItem(label, QString::number(id));
            else if (type == "sub") subBox_->addItem(label, QString::number(id));
        }
        if (audioBox_->count() == 0) audioBox_->addItem("Audio: Default", "auto");
    }

    void pollMpvEvents() {
        while (mpv_) {
            mpv_event *ev = mpv_wait_event(mpv_, 0);
            if (ev->event_id == MPV_EVENT_NONE) break;
            if (ev->event_id == MPV_EVENT_PROPERTY_CHANGE) {
                auto *prop = static_cast<mpv_event_property *>(ev->data);
                if (std::strcmp(prop->name, "duration") == 0 && prop->format == MPV_FORMAT_DOUBLE) {
                    duration_ = *static_cast<double *>(prop->data);
                    timeTot_->setText(fmtTime(duration_));
                } else if (std::strcmp(prop->name, "time-pos") == 0 && prop->format == MPV_FORMAT_DOUBLE) {
                    double pos = *static_cast<double *>(prop->data);
                    timeCur_->setText(fmtTime(pos));
                    if (!seeking_ && duration_ > 0.0) {
                        timeline_->setValue(static_cast<int>((pos / duration_) * 1000.0));
                    }
                } else if (std::strcmp(prop->name, "track-list") == 0 && prop->format == MPV_FORMAT_NODE) {
                    refreshTracks(static_cast<mpv_node *>(prop->data));
                }
            }
        }
    }

    mpv_handle *mpv_ = nullptr;
    PendingStreamStore streamStore_;
    MpvGlWidget *videoCanvas_ = nullptr;
    QLabel *overlayHint_ = nullptr;
    QLabel *timeCur_ = nullptr, *timeTot_ = nullptr;
    QSlider *timeline_ = nullptr, *volSlider_ = nullptr;
    QPushButton *playBtn_ = nullptr, *stopBtn_ = nullptr, *openBtn_ = nullptr, *fsBtn_ = nullptr;
    QComboBox *audioBox_ = nullptr, *subBox_ = nullptr;
    double duration_ = 0.0;
    bool seeking_ = false;
};

// ============================================================================
// 6. LAZY ZIP INSPECTOR (Reads Central Directory without full decryption!)
// ============================================================================

namespace ZipInspector {

struct ZipEntry {
    QString name;
    uint16_t method = 0; // 0 = Stored, 8 = Deflate
    uint32_t compSize = 0;
    uint32_t uncompSize = 0;
    uint32_t localHeaderOffset = 0;
    uint32_t crc32 = 0;
    bool isDir = false;
};

inline uint16_t rd16LE(const uint8_t *p) {
    return static_cast<uint16_t>(p[0]) | (static_cast<uint16_t>(p[1]) << 8);
}
inline uint32_t rd32LE(const uint8_t *p) {
    return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) |
           (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
}

inline uint32_t calculateCrc32(const uint8_t *data, size_t len) {
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; ++i) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
    }
    return ~crc;
}

template <typename ReadFn>
std::vector<ZipEntry> listEntries(uint64_t totalSize, ReadFn &&readAt) {
    constexpr uint64_t MAX_CD_BYTES = 16ULL * 1024 * 1024;
    constexpr uint16_t MAX_ENTRIES = 10000;
    if (totalSize < 22) throw std::runtime_error("File too small to be a ZIP archive.");
    const size_t tailLen = static_cast<size_t>(std::min<uint64_t>(totalSize, 65557));
    std::vector<uint8_t> tail(tailLen);
    if (!readAt(totalSize - tailLen, tail.data(), tailLen)) throw std::runtime_error("Failed to read ZIP tail.");
    int eocdPos = -1;
    for (int i = static_cast<int>(tailLen) - 22; i >= 0; --i) {
        if (rd32LE(tail.data() + i) == 0x06054b50u) {
            const uint16_t commentLen = rd16LE(tail.data() + i + 20);
            if (static_cast<size_t>(i) + 22 + commentLen == tailLen) { eocdPos = i; break; }
        }
    }
    OPENSSL_cleanse(tail.data(), tail.size());
    if (eocdPos < 0) throw std::runtime_error("ZIP End of Central Directory not found or invalid.");
    // Re-read the fixed EOCD record after validating its location.
    std::array<uint8_t, 22> eocd{};
    const uint64_t eocdOffset = totalSize - tailLen + static_cast<uint64_t>(eocdPos);
    if (!readAt(eocdOffset, eocd.data(), eocd.size())) throw std::runtime_error("Cannot read ZIP directory record.");
    if (rd16LE(eocd.data() + 4) != 0 || rd16LE(eocd.data() + 6) != 0 ||
        rd16LE(eocd.data() + 8) != rd16LE(eocd.data() + 10))
        throw std::runtime_error("Multi-disk ZIP archives are not supported.");
    const uint16_t totalEntries = rd16LE(eocd.data() + 10);
    const uint32_t cdSize = rd32LE(eocd.data() + 12);
    const uint32_t cdOffset = rd32LE(eocd.data() + 16);
    if (totalEntries == 0xFFFF || cdSize == 0xFFFFFFFFu || cdOffset == 0xFFFFFFFFu)
        throw std::runtime_error("ZIP64 archives are not supported by this safe previewer.");
    if (totalEntries > MAX_ENTRIES || cdSize > MAX_CD_BYTES ||
        static_cast<uint64_t>(cdOffset) + cdSize > eocdOffset)
        throw std::runtime_error("ZIP central directory exceeds safety limits or has invalid bounds.");
    std::vector<uint8_t> cd(cdSize);
    if (cdSize && !readAt(cdOffset, cd.data(), cdSize)) throw std::runtime_error("Failed to read ZIP Central Directory.");
    std::vector<ZipEntry> entries;
    entries.reserve(totalEntries);
    size_t pos = 0;
    for (uint16_t n = 0; n < totalEntries; ++n) {
        if (pos > cd.size() || cd.size() - pos < 46 || rd32LE(cd.data() + pos) != 0x02014b50u)
            throw std::runtime_error("Malformed ZIP central directory entry.");
        const uint16_t flags = rd16LE(cd.data() + pos + 8);
        ZipEntry e;
        e.method = rd16LE(cd.data() + pos + 10);
        e.crc32 = rd32LE(cd.data() + pos + 16);
        e.compSize = rd32LE(cd.data() + pos + 20);
        e.uncompSize = rd32LE(cd.data() + pos + 24);
        const uint16_t nameLen = rd16LE(cd.data() + pos + 28);
        const uint16_t extraLen = rd16LE(cd.data() + pos + 30);
        const uint16_t commentLen = rd16LE(cd.data() + pos + 32);
        e.localHeaderOffset = rd32LE(cd.data() + pos + 42);
        const uint64_t recLen = 46ULL + nameLen + extraLen + commentLen;
        if (recLen > cd.size() - pos) throw std::runtime_error("ZIP entry length exceeds central directory.");
        if ((flags & 0x0001u) || (flags & 0x0040u)) throw std::runtime_error("Encrypted ZIP entries are not supported.");
        if (e.compSize == 0xFFFFFFFFu || e.uncompSize == 0xFFFFFFFFu || e.localHeaderOffset == 0xFFFFFFFFu)
            throw std::runtime_error("ZIP64 entry is not supported.");
        e.name = QString::fromUtf8(reinterpret_cast<const char *>(cd.data() + pos + 46), nameLen);
        if (e.name.isEmpty() || e.name.contains(QChar::Null) || e.name.startsWith('/') || e.name.startsWith('\\') ||
            e.name.contains("../") || e.name == ".." || e.name.contains("/../") || e.name.contains("\\..\\"))
            throw std::runtime_error("Unsafe ZIP entry path rejected.");
        e.isDir = e.name.endsWith('/');
        if (e.method != 0 && e.method != 8) { /* listed, but extraction will refuse */ }
        if (e.uncompSize > 32u * 1024u * 1024u || (e.compSize == 0 && e.uncompSize != 0) ||
            (e.compSize > 0 && static_cast<uint64_t>(e.uncompSize) > static_cast<uint64_t>(e.compSize) * 200ULL))
            throw std::runtime_error("ZIP entry exceeds preview or compression-ratio limits.");
        if (static_cast<uint64_t>(e.localHeaderOffset) + 30 > totalSize)
            throw std::runtime_error("ZIP local header offset is outside archive.");
        entries.push_back(std::move(e));
        pos += static_cast<size_t>(recLen);
    }
    if (pos != cd.size()) throw std::runtime_error("Unexpected bytes in ZIP central directory.");
    if (!cd.empty()) OPENSSL_cleanse(cd.data(), cd.size());
    return entries;
}

template <typename ReadFn>
QByteArray extractEntryToRam(const ZipEntry &e, uint64_t totalSize, ReadFn &&readAt) {
    constexpr uint32_t MAX_PREVIEW_BYTES = 32 * 1024 * 1024;
    if (e.isDir) return {};
    if (e.uncompSize > MAX_PREVIEW_BYTES || e.compSize > MAX_PREVIEW_BYTES)
        throw std::runtime_error("Entry exceeds the 32 MiB compressed/decompressed preview limit.");
    uint8_t lh[30];
    if (static_cast<uint64_t>(e.localHeaderOffset) + 30 > totalSize ||
        !readAt(e.localHeaderOffset, lh, 30) || rd32LE(lh) != 0x04034b50u)
        throw std::runtime_error("Invalid ZIP local file header.");
    const uint16_t flags = rd16LE(lh + 6), method = rd16LE(lh + 8);
    const uint16_t nameLen = rd16LE(lh + 26), extraLen = rd16LE(lh + 28);
    if ((flags & 0x0001u) || method != e.method || static_cast<uint64_t>(e.localHeaderOffset) + 30ULL + nameLen + extraLen > totalSize)
        throw std::runtime_error("ZIP local/central header mismatch.");
    std::vector<uint8_t> localName(nameLen);
    if (nameLen && !readAt(static_cast<uint64_t>(e.localHeaderOffset) + 30, localName.data(), nameLen))
        throw std::runtime_error("Cannot read ZIP local filename.");
    const QString decodedLocalName = QString::fromUtf8(reinterpret_cast<const char *>(localName.data()), nameLen);
    if (decodedLocalName != e.name) throw std::runtime_error("ZIP local/central filename mismatch.");
    const uint64_t dataOff = static_cast<uint64_t>(e.localHeaderOffset) + 30ULL + nameLen + extraLen;
    if (dataOff > totalSize || e.compSize > totalSize - dataOff)
        throw std::runtime_error("ZIP compressed data lies outside archive.");
    QByteArray out;
    if (e.method == 0) {
        if (e.compSize != e.uncompSize) throw std::runtime_error("Invalid stored ZIP entry sizes.");
        out.resize(static_cast<int>(e.uncompSize));
        if (e.compSize && !readAt(dataOff, reinterpret_cast<uint8_t *>(out.data()), e.compSize))
            throw std::runtime_error("Failed to read stored ZIP entry.");
    } else if (e.method == 8) {
#ifdef HAVE_ZLIB
        std::vector<uint8_t> comp(e.compSize);
        if (e.compSize && !readAt(dataOff, comp.data(), e.compSize)) throw std::runtime_error("Failed to read compressed ZIP entry.");
        out.resize(static_cast<int>(e.uncompSize));
        z_stream zs{};
        zs.next_in = comp.data(); zs.avail_in = static_cast<uInt>(comp.size());
        zs.next_out = reinterpret_cast<Bytef *>(out.data()); zs.avail_out = static_cast<uInt>(out.size());
        if (inflateInit2(&zs, -MAX_WBITS) != Z_OK) { OPENSSL_cleanse(comp.data(), comp.size()); throw std::runtime_error("zlib init failed."); }
        const int ret = inflate(&zs, Z_FINISH);
        const bool exact = ret == Z_STREAM_END && zs.total_out == e.uncompSize && zs.total_in == e.compSize;
        inflateEnd(&zs);
        OPENSSL_cleanse(comp.data(), comp.size());
        if (!exact) { OPENSSL_cleanse(out.data(), static_cast<size_t>(out.size())); throw std::runtime_error("Deflate size or stream validation failed."); }
#else
        throw std::runtime_error("Deflate preview requires zlib support.");
#endif
    } else {
        throw std::runtime_error("Unsupported ZIP compression method.");
    }
    if (calculateCrc32(reinterpret_cast<const uint8_t *>(out.constData()), static_cast<size_t>(out.size())) != e.crc32) {
        OPENSSL_cleanse(out.data(), static_cast<size_t>(out.size()));
        throw std::runtime_error("ZIP CRC-32 validation failed.");
    }
    return out;
}

} // namespace ZipInspector

// ============================================================================
// 7. READ & PREVIEW PAGE (PDF, TXT, Images, Docs, & Lazy .fearfiles ZIPs)
// ============================================================================

class FearReadPage : public QWidget {
    Q_OBJECT
public:
    explicit FearReadPage(QWidget *parent = nullptr) : QWidget(parent) {
        setAcceptDrops(true);
        setStyleSheet("background:#F7F8F6; color:#1A1D1A;");

        auto *root = new QVBoxLayout(this);
        root->setContentsMargins(16, 14, 16, 14);
        root->setSpacing(10);

        auto *bar = new QHBoxLayout();
        auto *openBtn = new QPushButton("Open File / .fearfiles");
        auto *clearBtn = new QPushButton("Close & Wipe RAM");
        infoLbl_ = new QLabel("Drop any PDF, TXT, image, doc, ZIP, or .fearfiles here to preview in RAM.");
        infoLbl_->setStyleSheet("color:#5B615C; font-size:13px;");

        openBtn->setStyleSheet("QPushButton{background:#1F5C43; color:#fff; border:none; border-radius:6px; padding:7px 14px; font-weight:600;} QPushButton:hover{background:#174934;}");
        clearBtn->setStyleSheet("QPushButton{background:#FBEAE8; color:#B3261E; border:1px solid #B3261E; border-radius:6px; padding:6px 12px; font-weight:600;}");

        bar->addWidget(openBtn);
        bar->addWidget(clearBtn);
        bar->addSpacing(10);
        bar->addWidget(infoLbl_, 1);
        root->addLayout(bar);

        splitter_ = new QSplitter(Qt::Horizontal, this);

        zipTree_ = new QTreeWidget();
        zipTree_->setHeaderLabels({"File inside Archive", "Size", "Method"});
        zipTree_->header()->setSectionResizeMode(0, QHeaderView::Stretch);
        zipTree_->setStyleSheet("QTreeWidget{background:#FFFFFF; border:1px solid #D8DDD7; border-radius:8px;}");
        zipTree_->hide();
        splitter_->addWidget(zipTree_);

        previewStack_ = new QStackedWidget();
        previewStack_->setStyleSheet("background:#FFFFFF; border:1px solid #D8DDD7; border-radius:8px;");

        auto *emptyLbl = new QLabel("Drop any file here to read or inspect it.\n\n• PDF, TXT, Code, Images, Docs\n• Encrypted .fearfiles (zero-disk locked RAM preview)\n• .zip / .zip.fearfiles (browse files without full decryption)");
        emptyLbl->setAlignment(Qt::AlignCenter);
        emptyLbl->setStyleSheet("color:#6C7570; font-size:14px; border:none;");
        previewStack_->addWidget(emptyLbl);

        textView_ = new QPlainTextEdit();
        textView_->setReadOnly(true);
        textView_->setStyleSheet("QPlainTextEdit{font-family:Consolas,monospace; font-size:13px; padding:10px; border:none;}");
        previewStack_->addWidget(textView_);

        imageScroll_ = new QScrollArea();
        imageScroll_->setWidgetResizable(true);
        imageScroll_->setStyleSheet("border:none;");
        imageLbl_ = new QLabel();
        imageLbl_->setAlignment(Qt::AlignCenter);
        imageScroll_->setWidget(imageLbl_);
        previewStack_->addWidget(imageScroll_);

#ifdef HAVE_QT_PDF
        pdfDoc_ = new QPdfDocument(this);
        pdfView_ = new QPdfView(this);
        pdfView_->setDocument(pdfDoc_);
        pdfView_->setPageMode(QPdfView::PageMode::MultiPage);
        pdfView_->setZoomMode(QPdfView::ZoomMode::FitToWidth);
        previewStack_->addWidget(pdfView_);
#else
        auto *noPdfLbl = new QLabel("PDF preview requires Qt6::PdfWidgets.\nInstall qt6-webengine/qt6-pdf and rebuild to enable native PDF rendering.");
        noPdfLbl->setAlignment(Qt::AlignCenter);
        noPdfLbl->setStyleSheet("color:#6C7570; font-size:14px; border:none;");
        previewStack_->addWidget(noPdfLbl);
#endif

        splitter_->addWidget(previewStack_);
        splitter_->setStretchFactor(0, 1);
        splitter_->setStretchFactor(1, 2);
        root->addWidget(splitter_, 1);

        connect(openBtn, &QPushButton::clicked, this, [this]() {
            QString p = QFileDialog::getOpenFileName(this, "Open File to Read", "", "All Files (*)");
            if (!p.isEmpty()) openFile(p);
        });
        connect(clearBtn, &QPushButton::clicked, this, &FearReadPage::clearAndWipe);
        connect(zipTree_, &QTreeWidget::itemClicked, this, &FearReadPage::onZipItemClicked);
    }

    ~FearReadPage() override {
        clearAndWipe();
    }

    void clearAndWipe() {
        zipTree_->clear();
        zipTree_->hide();
        zipEntries_.clear();
        fearStream_.reset();
        plainZipPath_.clear();
        textView_->clear();
        imageLbl_->clear();
#ifdef HAVE_QT_PDF
        pdfDoc_->close();
#endif
        if (pdfBuf_) {
            pdfBuf_->close();
            pdfBuf_.reset();
        }
        wipeActiveRamBytes();
        previewStack_->setCurrentIndex(0);
        infoLbl_->setText("RAM wiped. Drop any file or .fearfiles to preview.");
    }

    void openFile(const QString &path) {
        clearAndWipe();
        try {
            if (FearCrypto::isFearFile(path)) {
                openEncryptedFearFile(path);
            } else {
                openPlainFile(path);
            }
        } catch (const std::exception &ex) {
            clearAndWipe();
            QMessageBox::critical(this, "Read Error", ex.what());
        }
    }

protected:
    void dragEnterEvent(QDragEnterEvent *e) override {
        if (e->mimeData()->hasUrls()) e->acceptProposedAction();
    }
    void dropEvent(QDropEvent *e) override {
        auto urls = e->mimeData()->urls();
        if (!urls.isEmpty()) openFile(urls.first().toLocalFile());
    }

private:
    void wipeActiveRamBytes() {
        if (!activeRamBytes_.isEmpty()) {
            OPENSSL_cleanse(activeRamBytes_.data(), static_cast<size_t>(activeRamBytes_.size()));
            if (ramBytesLocked_) {
                Security::unlockMemory(activeRamBytes_.data(), static_cast<size_t>(activeRamBytes_.size()));
                ramBytesLocked_ = false;
            }
            activeRamBytes_.clear();
        }
    }

    void setActiveRamBytes(QByteArray &&bytes) {
        wipeActiveRamBytes();
        activeRamBytes_ = std::move(bytes);
        if (!activeRamBytes_.isEmpty()) {
            ramBytesLocked_ = Security::lockMemory(activeRamBytes_.data(), static_cast<size_t>(activeRamBytes_.size()));
        }
    }

    static QString fmtBytes(uint64_t b) {
        if (b < 1024) return QString("%1 B").arg(b);
        if (b < 1024 * 1024) return QString("%1 KB").arg(b / 1024.0, 0, 'f', 1);
        return QString("%1 MB").arg(b / (1024.0 * 1024.0), 0, 'f', 2);
    }

    void openEncryptedFearFile(const QString &fearPath) {
        bool ok = false;
        QString qpw = QInputDialog::getText(
            this, "Unlock FEAR File for Reading",
            "Enter password to inspect:\n" + QFileInfo(fearPath).fileName(),
            QLineEdit::Password, "", &ok
        );
        if (!ok || qpw.isEmpty()) return;

        Security::SecureBuffer pwBuf;
        QByteArray utf8 = qpw.toUtf8();
        pwBuf.assignFromUtf8(utf8);
        OPENSSL_cleanse(utf8.data(), static_cast<size_t>(utf8.size()));
        qpw.fill(QChar('\0'));

        FearCrypto::ParsedHeader h = FearCrypto::openAndVerifyHeader(fearPath, pwBuf);
        pwBuf.wipeAndFree();

        auto stream = std::make_unique<FearMediaStream>();
        stream->file.open(fearPath.toStdString(), std::ios::binary);
        if (!stream->file) throw std::runtime_error("Cannot open .fearfiles for reading.");
        stream->totalChunks = std::max<uint64_t>(1, h.originalSize / h.chunkSize + (h.originalSize % h.chunkSize != 0));
        stream->h = std::move(h);

        const QString origName = stream->h.origName;
        const QString ext = QFileInfo(origName).suffix().toLower();

        if (ext == "zip") {
            fearStream_ = std::move(stream);
            zipEntries_ = ZipInspector::listEntries(fearStream_->h.originalSize,
                [this](uint64_t off, uint8_t *dst, size_t len) {
                    return fearStream_->readAt(off, dst, len);
                });
            populateZipTree(origName + " (Encrypted FEAR ZIP — lazy view, not fully decrypted)");
            return;
        }

        constexpr uint64_t MAX_RAM_PREVIEW = 32 * 1024 * 1024;
        if (stream->h.originalSize > MAX_RAM_PREVIEW) {
            throw std::runtime_error("File is larger than 32 MiB RAM preview limit. Use Decrypt tab.");
        }

        QByteArray buf(static_cast<int>(stream->h.originalSize), Qt::Uninitialized);
        if (stream->h.originalSize > 0 &&
            !stream->readAt(0, reinterpret_cast<uint8_t *>(buf.data()), static_cast<size_t>(stream->h.originalSize))) {
            OPENSSL_cleanse(buf.data(), static_cast<size_t>(buf.size()));
            throw std::runtime_error("Chunk authentication failed while reading into RAM.");
        }
        setActiveRamBytes(std::move(buf));
        previewBytes(origName + " (FEAR Locked RAM Preview)", origName, activeRamBytes_);
    }

    void openPlainFile(const QString &path) {
        QFileInfo fi(path);
        const QString ext = fi.suffix().toLower();

        if (ext == "zip") {
            plainZipPath_ = path;
            std::ifstream f(path.toStdString(), std::ios::binary | std::ios::ate);
            if (!f) throw std::runtime_error("Cannot open ZIP file.");
            uint64_t sz = static_cast<uint64_t>(f.tellg());
            zipEntries_ = ZipInspector::listEntries(sz, [&f](uint64_t off, uint8_t *dst, size_t len) {
                f.clear();
                f.seekg(static_cast<std::streamoff>(off), std::ios::beg);
                f.read(reinterpret_cast<char *>(dst), static_cast<std::streamsize>(len));
                return static_cast<size_t>(f.gcount()) == len;
            });
            populateZipTree(fi.fileName() + " (ZIP Archive)");
            return;
        }

        QFile f(path);
        if (!f.open(QIODevice::ReadOnly)) throw std::runtime_error("Cannot open file.");
        if (f.size() > 32 * 1024 * 1024) throw std::runtime_error("File exceeds 32 MiB preview limit.");
        setActiveRamBytes(f.readAll());
        previewBytes(fi.fileName(), fi.fileName(), activeRamBytes_);
    }

    void populateZipTree(const QString &title) {
        zipTree_->clear();
        for (int i = 0; i < static_cast<int>(zipEntries_.size()); ++i) {
            const auto &e = zipEntries_[i];
            auto *item = new QTreeWidgetItem(zipTree_);
            item->setText(0, e.name);
            item->setText(1, e.isDir ? "<DIR>" : fmtBytes(e.uncompSize));
            item->setText(2, e.isDir ? "" : (e.method == 0 ? "Stored" : (e.method == 8 ? "Deflate" : QString::number(e.method))));
            item->setData(0, Qt::UserRole, i);
        }
        zipTree_->show();
        infoLbl_->setText(QString("%1 — %2 item(s). Click any file to peek inside.").arg(title).arg(zipEntries_.size()));
        textView_->setPlainText("Select a file from the archive list on the left to preview it in RAM.");
        previewStack_->setCurrentIndex(1);
    }

    void onZipItemClicked(QTreeWidgetItem *item, int) {
        int idx = item->data(0, Qt::UserRole).toInt();
        if (idx < 0 || idx >= static_cast<int>(zipEntries_.size())) return;
        const auto &e = zipEntries_[idx];
        if (e.isDir) return;

        try {
            QByteArray extracted;
            if (fearStream_) {
                extracted = ZipInspector::extractEntryToRam(e, fearStream_->h.originalSize,
                    [this](uint64_t off, uint8_t *dst, size_t len) {
                        return fearStream_->readAt(off, dst, len);
                    });
            } else if (!plainZipPath_.isEmpty()) {
                std::ifstream f(plainZipPath_.toStdString(), std::ios::binary | std::ios::ate);
                uint64_t sz = static_cast<uint64_t>(f.tellg());
                extracted = ZipInspector::extractEntryToRam(e, sz, [&f](uint64_t off, uint8_t *dst, size_t len) {
                    f.clear();
                    f.seekg(static_cast<std::streamoff>(off), std::ios::beg);
                    f.read(reinterpret_cast<char *>(dst), static_cast<std::streamsize>(len));
                    return static_cast<size_t>(f.gcount()) == len;
                });
            }
            setActiveRamBytes(std::move(extracted));
            previewBytes(e.name + " (from archive)", e.name, activeRamBytes_);
        } catch (const std::exception &ex) {
            textView_->setPlainText(QString("Cannot preview '%1':\n%2").arg(e.name, ex.what()));
            previewStack_->setCurrentIndex(1);
        }
    }

    void previewBytes(const QString &label, const QString &filename, const QByteArray &data) {
        infoLbl_->setText(QString("%1 · %2").arg(label, fmtBytes(static_cast<uint64_t>(data.size()))));
        const QString ext = QFileInfo(filename).suffix().toLower();

        if (ext == "pdf") {
#ifdef HAVE_QT_PDF
            pdfDoc_->close();
            pdfBuf_ = std::make_unique<QBuffer>();
            pdfBuf_->setData(data);
            pdfBuf_->open(QIODevice::ReadOnly);
            pdfDoc_->load(pdfBuf_.get());
            previewStack_->setCurrentIndex(3);
#else
            previewStack_->setCurrentIndex(3);
#endif
            return;
        }

        static const QSet<QString> imgExts = {"png", "jpg", "jpeg", "bmp", "gif", "webp", "svg"};
        if (imgExts.contains(ext)) {
            QPixmap px;
            if (px.loadFromData(data)) {
                imageLbl_->setPixmap(px.scaled(900, 700, Qt::KeepAspectRatio, Qt::SmoothTransformation));
                previewStack_->setCurrentIndex(2);
                return;
            }
        }

        static const QSet<QString> textExts = {
            "txt","md","json","xml","html","htm","css","js","ts","cpp","c","h","hpp",
            "py","java","rs","go","sh","bat","ini","cfg","yaml","yml","toml","csv","log","sql","cmake"
        };
        if (textExts.contains(ext) || !data.contains('\0')) {
            textView_->setPlainText(QString::fromUtf8(data));
            previewStack_->setCurrentIndex(1);
            return;
        }

        QString hexOut = QString("Binary / Document file: %1 (%2)\nShowing first 4096 bytes (hex):\n\n")
                             .arg(filename, fmtBytes(static_cast<uint64_t>(data.size())));
        int limit = std::min(4096, static_cast<int>(data.size()));
        for (int i = 0; i < limit; i += 16) {
            hexOut += QString("%1: ").arg(i, 6, 16, QChar('0'));
            for (int j = 0; j < 16 && i + j < limit; ++j) {
                hexOut += QString("%1 ").arg(static_cast<unsigned char>(data[i + j]), 2, 16, QChar('0'));
            }
            hexOut += "\n";
        }
        textView_->setPlainText(hexOut);
        previewStack_->setCurrentIndex(1);
    }

    QLabel *infoLbl_ = nullptr;
    QSplitter *splitter_ = nullptr;
    QTreeWidget *zipTree_ = nullptr;
    QStackedWidget *previewStack_ = nullptr;
    QPlainTextEdit *textView_ = nullptr;
    QScrollArea *imageScroll_ = nullptr;
    QLabel *imageLbl_ = nullptr;
#ifdef HAVE_QT_PDF
    QPdfDocument *pdfDoc_ = nullptr;
    QPdfView *pdfView_ = nullptr;
#endif
    std::unique_ptr<QBuffer> pdfBuf_;
    QByteArray activeRamBytes_;
    bool ramBytesLocked_ = false;
    std::unique_ptr<FearMediaStream> fearStream_;
    QString plainZipPath_;
    std::vector<ZipInspector::ZipEntry> zipEntries_;
};

// ============================================================================
// 8. ENCRYPT / DECRYPT VAULT PANEL (Threaded Worker + Progress Bar)
// ============================================================================

class VaultWorker : public QThread {
    Q_OBJECT
public:
    VaultWorker(bool encryptMode, QStringList files, QString outDir, Security::SecureBuffer &&pw, QObject *parent = nullptr)
        : QThread(parent), enc_(encryptMode), files_(std::move(files)), outDir_(std::move(outDir)), pw_(std::move(pw)) {}

    ~VaultWorker() override {
        pw_.wipeAndFree();
    }

signals:
    void progressChanged(int percent, QString statusMsg);
    void jobFinished(int okCount, int failCount, QString lastError);

protected:
    void run() override {
        int ok = 0, fail = 0;
        QString lastErr;
        const int total = files_.size();

        for (int i = 0; i < total; ++i) {
            const QString &inPath = files_[i];
            const QString fname = QFileInfo(inPath).fileName();
            emit progressChanged(0, QString("%1 (%2/%3): %4").arg(enc_ ? "Encrypting" : "Decrypting").arg(i + 1).arg(total).arg(fname));

            try {
                auto cb = [this, i, total, fname](int pct) {
                    emit progressChanged(pct, QString("%1 (%2/%3): %4 — %5%").arg(enc_ ? "Encrypting" : "Decrypting").arg(i + 1).arg(total).arg(fname).arg(pct));
                };

                if (enc_) {
                    QString outPath = FearCrypto::makeUniquePath(outDir_, fname + ".fearfiles");
                    FearCrypto::encryptFile(inPath, outPath, pw_, cb);
                } else {
                    QString saved;
                    FearCrypto::decryptFileToDisk(inPath, outDir_, pw_, saved, cb);
                }
                ok++;
            } catch (const std::exception &ex) {
                fail++;
                lastErr = QString("Error on %1: %2").arg(fname, ex.what());
            }
        }
        pw_.wipeAndFree();
        emit jobFinished(ok, fail, lastErr);
    }

private:
    bool enc_;
    QStringList files_;
    QString outDir_;
    Security::SecureBuffer pw_;
};

class VaultPanel : public QWidget {
    Q_OBJECT
public:
    VaultPanel(bool encryptMode, QWidget *parent = nullptr) : QWidget(parent), enc_(encryptMode) {
        setAcceptDrops(true);
        auto *lay = new QVBoxLayout(this);
        lay->setContentsMargins(24, 20, 24, 20);
        lay->setSpacing(12);

        auto *title = new QLabel(enc_ ? "Encrypt Files (FEARW3)" : "Decrypt Files to Disk");
        title->setStyleSheet("font-size:17px; font-weight:700; color:#1A1D1A;");
        lay->addWidget(title);

        list_ = new QListWidget();
        list_->setStyleSheet("QListWidget{background:#F7F8F6; border:1.5px dashed #C9CDC5; border-radius:10px; padding:8px;}");
        lay->addWidget(list_, 1);

        auto *fileBtns = new QHBoxLayout();
        auto *addBtn = new QPushButton("Choose Files");
        auto *clrBtn = new QPushButton("Clear");
        fileBtns->addWidget(addBtn);
        fileBtns->addWidget(clrBtn);
        fileBtns->addStretch();
        lay->addLayout(fileBtns);

        pw1_ = new QLineEdit();
        pw1_->setEchoMode(QLineEdit::Password);
        pw1_->setPlaceholderText(enc_ ? "Password (min 16 characters)" : "Enter password");
        lay->addWidget(pw1_);

        if (enc_) {
            pw2_ = new QLineEdit();
            pw2_->setEchoMode(QLineEdit::Password);
            pw2_->setPlaceholderText("Confirm password");
            lay->addWidget(pw2_);
        }

        runBtn_ = new QPushButton(enc_ ? "Encrypt Selected Files" : "Decrypt & Save Files");
        runBtn_->setStyleSheet("QPushButton{background:#1F5C43; color:#fff; border:none; border-radius:7px; padding:12px; font-weight:600; font-size:14px;} QPushButton:hover{background:#174934;} QPushButton:disabled{background:#9AA39E;}");
        lay->addWidget(runBtn_);

        progress_ = new QProgressBar();
        progress_->setRange(0, 100);
        progress_->setValue(0);
        progress_->hide();
        lay->addWidget(progress_);

        status_ = new QLabel("");
        status_->setStyleSheet("color:#5B615C; font-size:13px;");
        lay->addWidget(status_);

        connect(addBtn, &QPushButton::clicked, this, [this]() {
            QStringList files = QFileDialog::getOpenFileNames(this, "Select Files");
            for (const auto &f : files) list_->addItem(f);
        });
        connect(clrBtn, &QPushButton::clicked, list_, &QListWidget::clear);
        connect(runBtn_, &QPushButton::clicked, this, &VaultPanel::runJob);
    }

    ~VaultPanel() override {
        if (worker_) {
            worker_->wait();
            delete worker_;
        }
    }

    void wipeInputs() {
        Security::scrubLineEdit(pw1_);
        Security::scrubLineEdit(pw2_);
    }

protected:
    void dragEnterEvent(QDragEnterEvent *e) override {
        if (e->mimeData()->hasUrls()) e->acceptProposedAction();
    }
    void dropEvent(QDropEvent *e) override {
        for (const auto &u : e->mimeData()->urls()) list_->addItem(u.toLocalFile());
    }

private slots:
    void runJob() {
        if (worker_ && worker_->isRunning()) return;
        if (list_->count() == 0) { status_->setText("Add at least one file first."); return; }

        QByteArray utf8 = pw1_->text().toUtf8();
        if (enc_) {
            if (utf8.size() < 16) {
                OPENSSL_cleanse(utf8.data(), static_cast<size_t>(utf8.size()));
                status_->setText("Use at least 16 characters.");
                return;
            }
            if (pw1_->text() != pw2_->text()) {
                OPENSSL_cleanse(utf8.data(), static_cast<size_t>(utf8.size()));
                status_->setText("Passwords do not match.");
                return;
            }
        } else if (utf8.isEmpty()) {
            status_->setText("Enter the password.");
            return;
        }

        Security::SecureBuffer pwBuf;
        pwBuf.assignFromUtf8(utf8);
        OPENSSL_cleanse(utf8.data(), static_cast<size_t>(utf8.size()));
        wipeInputs();

        QString outDir = QFileDialog::getExistingDirectory(this, "Select Output Folder");
        if (outDir.isEmpty()) {
            pwBuf.wipeAndFree();
            return;
        }

        QStringList files;
        for (int i = 0; i < list_->count(); ++i) files << list_->item(i)->text();

        runBtn_->setEnabled(false);
        progress_->setValue(0);
        progress_->show();

        worker_ = new VaultWorker(enc_, std::move(files), outDir, std::move(pwBuf), this);
        connect(worker_, &VaultWorker::progressChanged, this, [this](int pct, const QString &msg) {
            progress_->setValue(pct);
            status_->setText(msg);
        });
        connect(worker_, &VaultWorker::jobFinished, this, [this](int ok, int fail, const QString &lastErr) {
            runBtn_->setEnabled(true);
            progress_->hide();
            if (fail == 0) {
                status_->setText(QString("Done: %1 file(s) processed safely.").arg(ok));
            } else {
                status_->setText(QString("Finished with %1 ok, %2 failed. %3").arg(ok).arg(fail).arg(lastErr));
            }
            worker_->deleteLater();
            worker_ = nullptr;
        });
        worker_->start();
    }

private:
    bool enc_;
    QListWidget *list_ = nullptr;
    QLineEdit *pw1_ = nullptr, *pw2_ = nullptr;
    QPushButton *runBtn_ = nullptr;
    QProgressBar *progress_ = nullptr;
    QLabel *status_ = nullptr;
    VaultWorker *worker_ = nullptr;
};

// ============================================================================
// 9. MAIN WINDOW (Top Bar: Encrypt | Decrypt | FEARFiles Player | Read)
// ============================================================================

class FearMainWindow : public QMainWindow {
    Q_OBJECT
public:
    FearMainWindow() {
        setWindowTitle("FEAR — Private Encryption, Encrypted Player & Reader");
        resize(1060, 720);
        setStyleSheet("QMainWindow{background:#F7F8F6;}");

        auto *central = new QWidget(this);
        auto *root = new QVBoxLayout(central);
        root->setContentsMargins(0, 0, 0, 0);
        root->setSpacing(0);

        topBar_ = new QWidget(this);
        topBar_->setStyleSheet("background:#FFFFFF; border-bottom:1px solid #E1E4DF;");
        auto *barLay = new QHBoxLayout(topBar_);
        barLay->setContentsMargins(16, 10, 16, 10);

        auto *brand = new QLabel("FEAR Desktop");
        brand->setStyleSheet("font-size:17px; font-weight:700; color:#1F5C43;");
        barLay->addWidget(brand);
        barLay->addSpacing(16);

        btnEnc_ = new QPushButton("Encrypt");
        btnDec_ = new QPushButton("Decrypt");
        btnPlayer_ = new QPushButton("▶ FEARFiles Player");
        btnRead_ = new QPushButton("📖 Read");
        auto *lockBtn = new QPushButton("Lock & Wipe RAM");

        QString tabStyle = "QPushButton{background:#E7F0EB; color:#1F5C43; border:none; border-radius:7px; padding:8px 14px; font-weight:600;} QPushButton:hover{background:#1F5C43; color:#fff;}";
        btnEnc_->setStyleSheet(tabStyle);
        btnDec_->setStyleSheet(tabStyle);
        btnPlayer_->setStyleSheet("QPushButton{background:#1F5C43; color:#fff; border:none; border-radius:7px; padding:8px 16px; font-weight:700;} QPushButton:hover{background:#174934;}");
        btnRead_->setStyleSheet(tabStyle);
        lockBtn->setStyleSheet("QPushButton{background:#FBEAE8; color:#B3261E; border:1px solid #B3261E; border-radius:7px; padding:7px 12px; font-weight:600;}");

        barLay->addWidget(btnEnc_);
        barLay->addWidget(btnDec_);
        barLay->addWidget(btnPlayer_);
        barLay->addWidget(btnRead_);
        barLay->addStretch();
        barLay->addWidget(lockBtn);
        root->addWidget(topBar_);

        stack_ = new QStackedWidget(this);
        encPage_ = new VaultPanel(true, this);
        decPage_ = new VaultPanel(false, this);
        playerPage_ = new FearPlayerPage(this);
        readPage_ = new FearReadPage(this);

        stack_->addWidget(encPage_);
        stack_->addWidget(decPage_);
        stack_->addWidget(playerPage_);
        stack_->addWidget(readPage_);
        root->addWidget(stack_, 1);
        setCentralWidget(central);

        connect(btnEnc_, &QPushButton::clicked, this, [this]() { switchPage(0); });
        connect(btnDec_, &QPushButton::clicked, this, [this]() { switchPage(1); });
        connect(btnPlayer_, &QPushButton::clicked, this, [this]() { switchPage(2); });
        connect(btnRead_, &QPushButton::clicked, this, [this]() { switchPage(3); });
        connect(lockBtn, &QPushButton::clicked, this, [this]() {
            encPage_->wipeInputs();
            decPage_->wipeInputs();
            playerPage_->stopAndWipe();
            readPage_->clearAndWipe();
        });
        connect(playerPage_, &FearPlayerPage::toggleFullscreenRequested, this, &FearMainWindow::togglePlayerFullscreen);

        Security::protectWindowFromCapture(this);
    }

protected:
    void keyPressEvent(QKeyEvent *e) override {
        if (stack_->currentIndex() == 2) {
            if (e->key() == Qt::Key_Escape && isFullScreen()) togglePlayerFullscreen();
            else if (e->key() == Qt::Key_F) togglePlayerFullscreen();
            else if (e->key() == Qt::Key_Space) playerPage_->togglePause();
        }
        QMainWindow::keyPressEvent(e);
    }

    void closeEvent(QCloseEvent *e) override {
        encPage_->wipeInputs();
        decPage_->wipeInputs();
        playerPage_->stopAndWipe();
        readPage_->clearAndWipe();
        QMainWindow::closeEvent(e);
    }

private:
    void switchPage(int idx) {
        encPage_->wipeInputs();
        decPage_->wipeInputs();
        if (idx != 2) playerPage_->stopAndWipe();
        if (idx != 3) readPage_->clearAndWipe();
        stack_->setCurrentIndex(idx);
    }

    void togglePlayerFullscreen() {
        if (isFullScreen()) {
            topBar_->show();
            showNormal();
        } else {
            topBar_->hide();
            showFullScreen();
        }
    }

    QWidget *topBar_ = nullptr;
    QStackedWidget *stack_ = nullptr;
    QPushButton *btnEnc_ = nullptr, *btnDec_ = nullptr, *btnPlayer_ = nullptr, *btnRead_ = nullptr;
    VaultPanel *encPage_ = nullptr, *decPage_ = nullptr;
    FearPlayerPage *playerPage_ = nullptr;
    FearReadPage *readPage_ = nullptr;
};

#include "fearfiles_desktop.moc"

int main(int argc, char *argv[]) {
    Security::hardenProcess();

    QApplication app(argc, argv);
    std::setlocale(LC_NUMERIC, "C");

    FearMainWindow win;
    win.show();
    return app.exec();
}