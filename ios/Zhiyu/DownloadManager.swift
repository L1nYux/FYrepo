import UIKit
import WebKit

final class DownloadManager: NSObject, URLSessionDownloadDelegate {
    static var folder: URL { FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("Downloads", isDirectory: true) }
    private weak var controller: MainController?
    private var task: URLSessionDownloadTask?
    private var session: URLSession?
    private var sheet: UIAlertController?
    private let progress = UIProgressView(progressViewStyle: .bar)
    private var destinationName = "文件"
    private var openAfter = false
    private var generation = 0
    private var transferred = false
    init(controller: MainController) { self.controller = controller }
    func cancel() {
        generation += 1
        task = nil
        session?.invalidateAndCancel()
        session = nil
        sheet?.dismiss(animated: true)
        sheet = nil
    }
    func start(url: URL, name: String, open: Bool) {
        guard let controller, controller.trusted(url), controller.trusted(controller.webView.url) else { return }
        if task != nil { controller.notice("已有文件正在下载，请先完成或取消。"); return }
        generation += 1
        let epoch = generation
        let cleaned = name.components(separatedBy: CharacterSet(charactersIn: "/\\:").union(.controlCharacters)).joined(separator: "_")
        destinationName = cleaned.isEmpty || cleaned == "." || cleaned == ".." ? "文件" : String(cleaned.prefix(180))
        openAfter = open
        controller.webView.configuration.websiteDataStore.httpCookieStore.getAllCookies { [weak self, weak controller] cookies in
            guard let self, let controller, self.generation == epoch, controller.trusted(url) else { return }
            var request = URLRequest(url: url)
            // The cookie store belongs to this app and this configured origin.
            // URLSession redirects are checked again before credentials can leave it.
            let host = url.host?.lowercased() ?? ""
            let selected = cookies.filter { cookie in
                let domain = cookie.domain.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "."))
                return (host == domain || host.hasSuffix("." + domain)) && url.path.hasPrefix(cookie.path) && (!cookie.isSecure || url.scheme == "https") && (cookie.expiresDate == nil || cookie.expiresDate! > Date())
            }
            request.allHTTPHeaderFields = HTTPCookie.requestHeaderFields(with: selected)
            request.setValue("ZhiyuMobile/iOS", forHTTPHeaderField: "User-Agent")
            let config = URLSessionConfiguration.ephemeral
            config.httpCookieStorage = nil
            config.urlCredentialStorage = nil
            config.timeoutIntervalForResource = 600
            self.session = URLSession(configuration: config, delegate: self, delegateQueue: .main)
            let task = self.session!.downloadTask(with: request)
            self.task = task
            self.transferred = false
            let sheet = UIAlertController(title: "下载文件", message: self.destinationName + "\n\n", preferredStyle: .alert)
            self.progress.progress = 0
            self.progress.frame = CGRect(x: 20, y: 82, width: 230, height: 4)
            self.progress.autoresizingMask = .flexibleWidth
            sheet.view.addSubview(self.progress)
            sheet.addAction(UIAlertAction(title: "取消下载", style: .cancel) { _ in self.cancel() })
            self.sheet = sheet
            controller.present(sheet, animated: true)
            task.resume()
        }
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        guard controller?.trusted(request.url) == true else { completionHandler(nil); return }
        completionHandler(request)
    }
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didWriteData bytesWritten: Int64, totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        if totalBytesWritten > 512 * 1024 * 1024 { downloadTask.cancel(); return }
        if totalBytesExpectedToWrite > 0 {
            let ratio = min(0.99, Float(totalBytesWritten) / Float(totalBytesExpectedToWrite))
            progress.progress = ratio
            sheet?.message = destinationName + " · \(Int(ratio * 100))%\n\n"
        } else { sheet?.message = destinationName + " · \(ByteCountFormatter.string(fromByteCount: totalBytesWritten, countStyle: .file))\n\n" }
    }
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        guard task === downloadTask, let controller, let response = downloadTask.response as? HTTPURLResponse, response.statusCode == 200, controller.trusted(response.url), response.url?.path != "/login/" else { return }
        if response.mimeType == "text/html" && !(response.value(forHTTPHeaderField: "Content-Disposition") ?? "").lowercased().contains("attachment") { return }
        do {
            try FileManager.default.createDirectory(at: Self.folder, withIntermediateDirectories: true)
            let attributes = try FileManager.default.attributesOfItem(atPath: location.path)
            guard ((attributes[.size] as? NSNumber)?.int64Value ?? 0) <= 512 * 1024 * 1024 else { return }
            let original = Self.folder.appendingPathComponent(destinationName)
            let target = FileManager.default.fileExists(atPath: original.path) ? original.deletingPathExtension().appendingPathExtension(String(Int(Date().timeIntervalSince1970)) + "." + original.pathExtension) : original
            try FileManager.default.moveItem(at: location, to: target)
            transferred = true
            progress.progress = 1
            let open = openAfter
            sheet?.dismiss(animated: true) {
                if open { controller.open(target) }
                else { controller.toast("已保存到知域") }
            }
        } catch { transferred = false }
    }
    func urlSession(_ session: URLSession, task completedTask: URLSessionTask, didCompleteWithError error: Error?) {
        guard task === completedTask else { return }
        let done = transferred
        task = nil
        session.finishTasksAndInvalidate()
        self.session = nil
        if !done {
            sheet?.dismiss(animated: true) { [weak self] in
                if (error as NSError?)?.code != NSURLErrorCancelled { self?.controller?.notice("文件下载失败，请检查连接后重试。") }
            }
        }
        sheet = nil
    }
}

final class DownloadsController: UITableViewController {
    private weak var main: MainController?
    private var files: [URL] = []
    init(main: MainController) { self.main = main; super.init(style: .insetGrouped) }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override func viewDidLoad() { super.viewDidLoad(); title = "已下载文件"; reload() }
    private func reload() { files = (try? FileManager.default.contentsOfDirectory(at: DownloadManager.folder, includingPropertiesForKeys: [.fileSizeKey], options: [.skipsHiddenFiles])) ?? []; files.sort { $0.lastPathComponent < $1.lastPathComponent }; tableView.reloadData() }
    override func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int { max(1, files.count) }
    override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = UITableViewCell(style: .subtitle, reuseIdentifier: nil)
        if files.isEmpty { cell.textLabel?.text = "暂无下载文件"; cell.selectionStyle = .none }
        else { let file = files[indexPath.row]; cell.textLabel?.text = file.lastPathComponent; cell.textLabel?.numberOfLines = 2; cell.imageView?.image = UIImage(systemName: "doc"); cell.accessoryType = .disclosureIndicator; let size = (try? file.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0; cell.detailTextLabel?.text = ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file) }
        return cell
    }
    override func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) { if files.indices.contains(indexPath.row) { main?.open(files[indexPath.row]) }; tableView.deselectRow(at: indexPath, animated: true) }
    override func tableView(_ tableView: UITableView, trailingSwipeActionsConfigurationForRowAt indexPath: IndexPath) -> UISwipeActionsConfiguration? {
        guard files.indices.contains(indexPath.row) else { return nil }
        let file = files[indexPath.row]
        let share = UIContextualAction(style: .normal, title: "分享") { _, _, finish in
            let sheet = UIActivityViewController(activityItems: [file], applicationActivities: nil); sheet.popoverPresentationController?.sourceView = self.view; self.present(sheet, animated: true); finish(true)
        }
        let remove = UIContextualAction(style: .destructive, title: "删除") { _, _, finish in
            let alert = UIAlertController(title: "删除本机文件？", message: file.lastPathComponent, preferredStyle: .alert)
            alert.addAction(UIAlertAction(title: "取消", style: .cancel) { _ in finish(false) })
            alert.addAction(UIAlertAction(title: "删除", style: .destructive) { _ in do { try FileManager.default.removeItem(at: file); self.reload(); finish(true) } catch { finish(false) } })
            self.present(alert, animated: true)
        }
        let actions = UISwipeActionsConfiguration(actions: [remove, share]); actions.performsFirstActionWithFullSwipe = false; return actions
    }
}
