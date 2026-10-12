import UIKit
import WebKit
import QuickLook

final class MainController: UIViewController, WKNavigationDelegate, WKUIDelegate, UITabBarDelegate, QLPreviewControllerDataSource {
    private(set) var webView: WKWebView!
    private var server = URL(string: UserDefaults.standard.string(forKey: "server") ?? "http://47.117.89.248")!
    private let tabs = UITabBar()
    private let progress = UIProgressView(progressViewStyle: .bar)
    private let errorLabel = UILabel()
    private var observation: NSKeyValueObservation?
    private var previewURL: URL?
    private var webBottom: NSLayoutConstraint!
    private var tabsHeight: NSLayoutConstraint!
    private var keyboardOverlap: CGFloat = 0
    private lazy var downloads = DownloadManager(controller: self)
    private let routes = ["/messages/social/", "/workspace/", "/assistant/", "/discover/", "/me/"]

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground
        let configuration = WKWebViewConfiguration()
        configuration.applicationNameForUserAgent = "ZhiyuMobile/iOS"
        configuration.websiteDataStore = .default()
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = true
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.translatesAutoresizingMaskIntoConstraints = false
        tabs.translatesAutoresizingMaskIntoConstraints = false
        tabs.delegate = self
        tabs.items = zip(["消息", "工作台", "AI", "发现", "我"], ["bubble.left", "square.grid.2x2", "sparkles", "safari", "person"]).enumerated().map { index, item in
            UITabBarItem(title: item.0, image: UIImage(systemName: item.1), tag: index)
        }
        tabs.selectedItem = tabs.items?.first
        view.tintColor = UIColor(red: 0.03, green: 0.61, blue: 0.38, alpha: 1)
        navigationItem.rightBarButtonItem = UIBarButtonItem(image: UIImage(systemName: "ellipsis"), style: .plain, target: self, action: #selector(showMenu))
        [webView!, tabs, progress, errorLabel].forEach { view.addSubview($0) }
        progress.translatesAutoresizingMaskIntoConstraints = false
        errorLabel.translatesAutoresizingMaskIntoConstraints = false
        errorLabel.numberOfLines = 0
        errorLabel.textAlignment = .center
        errorLabel.isHidden = true
        errorLabel.isUserInteractionEnabled = true
        errorLabel.addGestureRecognizer(UITapGestureRecognizer(target: self, action: #selector(retry)))
        webBottom = webView.bottomAnchor.constraint(equalTo: tabs.topAnchor)
        tabsHeight = tabs.heightAnchor.constraint(equalToConstant: 52)
        NSLayoutConstraint.activate([
            webView.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
            webView.leadingAnchor.constraint(equalTo: view.leadingAnchor), webView.trailingAnchor.constraint(equalTo: view.trailingAnchor), webBottom,
            tabs.leadingAnchor.constraint(equalTo: view.leadingAnchor), tabs.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            tabs.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor), tabsHeight,
            progress.topAnchor.constraint(equalTo: webView.topAnchor), progress.leadingAnchor.constraint(equalTo: view.leadingAnchor), progress.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            errorLabel.centerXAnchor.constraint(equalTo: view.centerXAnchor), errorLabel.centerYAnchor.constraint(equalTo: view.centerYAnchor),
            errorLabel.leadingAnchor.constraint(greaterThanOrEqualTo: view.leadingAnchor, constant: 24), errorLabel.trailingAnchor.constraint(lessThanOrEqualTo: view.trailingAnchor, constant: -24)
        ])
        observation = webView.observe(\.estimatedProgress, options: [.new]) { [weak self] _, change in
            guard let self else { return }
            self.progress.progress = Float(change.newValue ?? 0)
            self.progress.isHidden = self.webView.estimatedProgress >= 1
        }
        NotificationCenter.default.addObserver(self, selector: #selector(keyboardChanged(_:)), name: UIResponder.keyboardWillChangeFrameNotification, object: nil)
        load(routes[0])
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        syncViewport()
    }
    func trusted(_ url: URL?) -> Bool {
        guard let url else { return false }
        let port: (URL) -> Int = { $0.port ?? ($0.scheme == "https" ? 443 : 80) }
        return ["http", "https"].contains(url.scheme ?? "") && url.scheme == server.scheme && url.host?.lowercased() == server.host?.lowercased() && port(url) == port(server) && url.user == nil && url.password == nil
    }
    private func load(_ route: String) {
        guard let url = URL(string: route, relativeTo: server)?.absoluteURL, trusted(url) else { return }
        errorLabel.isHidden = true
        webView.load(URLRequest(url: url))
    }
    @objc private func retry() { errorLabel.isHidden = true; webView.reload() }
    @objc private func back() { if webView.canGoBack { webView.goBack() } else { load(routes[1]) } }
    private func syncViewport() {
        guard trusted(webView?.url), webView.bounds.height > 0 else { return }
        webView.evaluateJavaScript("window.zhiyuPhoneViewport?.(\(webView.bounds.height),\(webBottom.constant < 0));", completionHandler: nil)
    }
    @objc private func keyboardChanged(_ notice: Notification) {
        guard let frame = notice.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect else { return }
        let keyboard = view.convert(frame, from: nil)
        let overlap = max(0, view.bounds.maxY - keyboard.minY - view.safeAreaInsets.bottom)
        keyboardOverlap = overlap
        webBottom.constant = -max(0, overlap - tabsHeight.constant)
        UIView.animate(withDuration: 0.25) { self.view.layoutIfNeeded() }
        syncViewport()
    }
    func tabBar(_ tabBar: UITabBar, didSelect item: UITabBarItem) {
        guard routes.indices.contains(item.tag) else { return }
        webView.evaluateJavaScript("Boolean(document.querySelector('[data-message-input],.conversation-composer textarea,#assistant-input')?.value.trim())") { [weak self] result, _ in
            guard let self else { return }
            if result as? Bool == true {
                self.confirm("有尚未发送的内容，离开当前页面？") { if $0 { self.load(self.routes[item.tag]) } }
            } else { self.load(self.routes[item.tag]) }
        }
    }
    private func bars(_ url: URL) {
        let path = url.path
        let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        let headings = [("/api-pool/manage/", "API 池管理"), ("/api-pool/", query.contains { $0.name == "scope" && $0.value == "team" } ? "额度与用量" : "用量与额度"), ("/messages/", "消息"), ("/projects/", "项目"), ("/tasks/", "任务"), ("/documents/", "文档"), ("/experiments/", "实验"), ("/account/", "设置"), ("/discover/", "发现"), ("/me/", "我"), ("/workspace/", "工作台")]
        title = headings.first { path.hasPrefix($0.0) }?.1 ?? "知域"
        let chat = path.range(of: "^/messages/(personal|groups)/[1-9][0-9]*/$", options: .regularExpression) != nil
        navigationController?.setNavigationBarHidden(chat || path == "/assistant/", animated: false)
        navigationItem.leftBarButtonItem = routes.contains(path) ? nil : UIBarButtonItem(image: UIImage(systemName: "chevron.left"), style: .plain, target: self, action: #selector(back))
        if let index = routes.firstIndex(where: { path.hasPrefix("/" + String($0.split(separator: "/")[0]) + "/") }) { tabs.selectedItem = tabs.items?[index] }
        tabs.isHidden = chat || path == "/login/" || path == "/register/"
        tabsHeight.constant = tabs.isHidden ? 0 : 52
        webBottom.constant = -max(0, keyboardOverlap - tabsHeight.constant)
    }
    private func bootstrap() {
        guard trusted(webView.url), let base = Bundle.main.resourceURL?.appendingPathComponent("PhoneAssets") else { return }
        do {
            let css = try ["mobile.css", "phone-layout.css"].map { try String(contentsOf: base.appendingPathComponent($0), encoding: .utf8) }.joined(separator: "\n")
            let scripts = try ["phone-interactions.js", "mobile.js", "phone-assistant.js", "local-chat.js", "phone-layout.js"].map { try String(contentsOf: base.appendingPathComponent($0), encoding: .utf8) }.joined(separator: "\n")
            let encoded = String(data: try JSONSerialization.data(withJSONObject: [css]), encoding: .utf8)!
            let injection = "(()=>{let s=document.getElementById('zhiyu-phone-css');if(!s){s=document.createElement('style');s.id='zhiyu-phone-css';document.head.append(s);}s.textContent=(\(encoded))[0];\n\(scripts)\n})();"
            webView.evaluateJavaScript(injection) { [weak self] _, error in
                if let error { self?.showError("手机页面未能准备完成：\(error.localizedDescription)") }
                else { self?.syncViewport() }
            }
        } catch { showError("缺少手机页面资源，请重新安装。") }
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard let url = webView.url, trusted(url) else { return }
        errorLabel.isHidden = true
        bars(url)
        bootstrap()
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { failed(error) }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { failed(error) }
    private func failed(_ error: Error) {
        if (error as NSError).code != NSURLErrorCancelled { showError("暂时连接不上服务器。\n轻点重试，或通过右上角更换连接。") }
    }
    private func showError(_ text: String) { errorLabel.text = text; errorLabel.isHidden = false; progress.isHidden = true }
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if trusted(url) {
            let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
            if url.path == "/app/pages/" && query.contains(where: { $0.name == "view" && $0.value == "scan" }) {
                decisionHandler(.cancel)
                if action.sourceFrame.isMainFrame && trusted(action.sourceFrame.request.url) { scan() }
                return
            }
            if url.path.hasPrefix("/__phone_") {
                decisionHandler(.cancel)
                if action.sourceFrame.isMainFrame && trusted(action.sourceFrame.request.url) { nativeAction(url) }
                return
            }
            if action.shouldPerformDownload { decisionHandler(.cancel); downloads.start(url: url, name: url.lastPathComponent, open: false); return }
            decisionHandler(.allow)
        } else if url.scheme == "about" && url.absoluteString == "about:blank" { decisionHandler(.allow) }
        else {
            decisionHandler(.cancel)
            if action.targetFrame?.isMainFrame != false { external(url) }
        }
    }
    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        guard response.isForMainFrame, let http = response.response as? HTTPURLResponse, let url = http.url else { decisionHandler(.allow); return }
        if http.statusCode >= 500 { showError("服务器暂时不可用（\(http.statusCode)）。\n轻点重试。") }
        let attachment = (http.value(forHTTPHeaderField: "Content-Disposition") ?? "").lowercased().hasPrefix("attachment")
        if trusted(url) && (attachment || !response.canShowMIMEType) {
            decisionHandler(.cancel); downloads.start(url: url, name: response.response.suggestedFilename ?? "文件", open: false)
        } else { decisionHandler(.allow) }
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { if trusted(url) { webView.load(action.request) } else { external(url) } }
        return nil
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        guard trusted(frame.request.url) else { completionHandler(); return }
        notice(message, completed: completionHandler)
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        guard trusted(frame.request.url) else { completionHandler(false); return }
        confirm(message, completed: completionHandler)
    }
    private func nativeAction(_ url: URL) {
        guard trusted(webView.url) else { return }
        let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        func value(_ name: String) -> String? { items.first { $0.name == name }?.value }
        switch url.path {
        case "/__phone_copy__/": if let text = value("text"), text.count <= 30000 { UIPasteboard.general.string = text; toast("已复制") }
        case "/__phone_file_open__/": if let address = value("url"), let target = URL(string: address), trusted(target) { downloads.start(url: target, name: value("name") ?? "文件", open: true) }
        case "/__phone_connection__/": showConnection()
        case "/__phone_settings__/": showMenu()
        case "/__phone_scan__/": scan()
        case "/__phone_backup__/": backup()
        case "/__phone_update__/": external(URL(string: "https://github.com/L1nYux/FYrepo/releases")!)
        case "/__phone_background__/": notice("当前 iPhone 版在应用打开时收取消息，暂未接入后台推送。")
        case "/__phone_accent__/":
            let colors: [String: UIColor] = ["green": UIColor(red: 0.03, green: 0.61, blue: 0.38, alpha: 1), "blue": .systemBlue, "purple": .systemPurple, "orange": .systemOrange, "pink": .systemPink]
            if let name = value("name"), let color = colors[name] { view.tintColor = color }
        default: break
        }
    }
    @objc private func showMenu() {
        let sheet = UIAlertController(title: "知域", message: "iPhone 0.6.3 · 需要自行签名安装", preferredStyle: .actionSheet)
        sheet.addAction(UIAlertAction(title: "扫一扫", style: .default) { _ in self.scan() })
        sheet.addAction(UIAlertAction(title: "连接设置", style: .default) { _ in self.showConnection() })
        sheet.addAction(UIAlertAction(title: "已下载文件", style: .default) { _ in self.navigationController?.pushViewController(DownloadsController(main: self), animated: true) })
        sheet.addAction(UIAlertAction(title: "取消", style: .cancel))
        anchor(sheet)
        present(sheet, animated: true)
    }
    private func showConnection() {
        let sheet = UIAlertController(title: "连接服务器", message: "填写团队的知域服务器地址。切换后需要重新登录。", preferredStyle: .alert)
        sheet.addTextField { field in field.text = self.server.absoluteString; field.keyboardType = .URL; field.autocapitalizationType = .none; field.autocorrectionType = .no }
        sheet.addAction(UIAlertAction(title: "取消", style: .cancel))
        sheet.addAction(UIAlertAction(title: "连接", style: .default) { _ in
            guard let text = sheet.textFields?.first?.text?.trimmingCharacters(in: .whitespacesAndNewlines), let parts = URLComponents(string: text), ["http", "https"].contains(parts.scheme ?? ""), let host = parts.host, !host.isEmpty, parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil, ["", "/"].contains(parts.path), let address = parts.url else { self.notice("请输入完整的 http:// 或 https:// 服务器地址。") ; return }
            self.downloads.cancel()
            self.webView.stopLoading()
            let store = WKWebsiteDataStore.default().httpCookieStore
            store.getAllCookies { cookies in
                let group = DispatchGroup()
                for cookie in cookies { group.enter(); store.delete(cookie) { group.leave() } }
                group.notify(queue: .main) {
                self.server = address
                UserDefaults.standard.set(address.absoluteString, forKey: "server")
                self.load(self.routes[0])
                }
            }
        })
        present(sheet, animated: true)
    }
    private func scan() {
        let scanner = ScannerController()
        scanner.onCode = { [weak self] code in
            guard let self, self.trusted(self.webView.url), let data = try? JSONSerialization.data(withJSONObject: [code]), let encoded = String(data: data, encoding: .utf8) else { return }
            self.webView.evaluateJavaScript("window.zhiyuExperience?.scanResult((\(encoded))[0]);", completionHandler: nil)
        }
        present(UINavigationController(rootViewController: scanner), animated: true)
    }
    private func backup() {
        webView.callAsyncJavaScript("if(!window.zhiyuPrepareChatBackup)throw Error('请先打开聊天记录管理');await window.zhiyuPrepareChatBackup();if(window.zhiyuChatBackup.error)throw Error(window.zhiyuChatBackup.error);return window.zhiyuChatBackup.text;", arguments: [:], in: nil, in: .page) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let value):
                guard let text = value as? String, let data = text.data(using: .utf8), data.count <= 20 * 1024 * 1024 else { self.notice("备份超出大小限制。"); return }
                let destination = DownloadManager.folder.appendingPathComponent("知域聊天备份-\(Int(Date().timeIntervalSince1970)).json")
                do { try FileManager.default.createDirectory(at: DownloadManager.folder, withIntermediateDirectories: true); try data.write(to: destination, options: .atomic); self.share(destination) }
                catch { self.notice("无法保存备份：\(error.localizedDescription)") }
            case .failure: self.notice("请先打开聊天记录管理，再导出备份。")
            }
        }
    }
    private func external(_ url: URL) {
        guard ["https", "http", "mailto", "tel"].contains(url.scheme ?? "") else { notice("无法打开此链接。"); return }
        confirm("用系统应用打开\(url.host.map { "“\($0)”" } ?? "此链接")？") { if $0 { UIApplication.shared.open(url) } }
    }
    func notice(_ message: String, completed: (() -> Void)? = nil) {
        let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "知道了", style: .default) { _ in completed?() })
        present(alert, animated: true)
    }
    func toast(_ text: String) {
        let label = UILabel()
        label.text = text
        label.textColor = .white
        label.backgroundColor = UIColor.black.withAlphaComponent(0.78)
        label.textAlignment = .center
        label.font = .systemFont(ofSize: 14)
        label.layer.cornerRadius = 10
        label.clipsToBounds = true
        label.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(label)
        NSLayoutConstraint.activate([label.centerXAnchor.constraint(equalTo: view.centerXAnchor), label.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -70), label.heightAnchor.constraint(equalToConstant: 40), label.widthAnchor.constraint(equalToConstant: min(view.bounds.width - 40, max(120, CGFloat(text.count) * 15 + 32)))])
        UIView.animate(withDuration: 0.25, delay: 2, options: []) { label.alpha = 0 } completion: { _ in label.removeFromSuperview() }
    }
    func confirm(_ message: String, completed: @escaping (Bool) -> Void) {
        let alert = UIAlertController(title: "请确认", message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "取消", style: .cancel) { _ in completed(false) })
        alert.addAction(UIAlertAction(title: "确认", style: .default) { _ in completed(true) })
        present(alert, animated: true)
    }
    func anchor(_ controller: UIViewController) {
        controller.popoverPresentationController?.sourceView = view
        controller.popoverPresentationController?.sourceRect = CGRect(x: view.bounds.midX, y: view.bounds.maxY - 40, width: 1, height: 1)
    }
    func open(_ url: URL) {
        previewURL = url
        let preview = QLPreviewController(); preview.dataSource = self
        (navigationController?.topViewController ?? self).present(preview, animated: true)
    }
    func share(_ url: URL) { let sheet = UIActivityViewController(activityItems: [url], applicationActivities: nil); anchor(sheet); present(sheet, animated: true) }
    func numberOfPreviewItems(in controller: QLPreviewController) -> Int { previewURL == nil ? 0 : 1 }
    func previewController(_ controller: QLPreviewController, previewItemAt index: Int) -> QLPreviewItem { previewURL! as NSURL }
}
