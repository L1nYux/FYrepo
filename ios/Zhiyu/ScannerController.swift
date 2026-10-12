import UIKit
import AVFoundation

final class ScannerController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    var onCode: ((String) -> Void)?
    private let capture = AVCaptureSession()
    private let queue = DispatchQueue(label: "org.fyrepo.zhiyu.scanner")
    private var layer: AVCaptureVideoPreviewLayer?
    private var finished = false
    override func viewDidLoad() {
        super.viewDidLoad()
        title = "扫一扫"
        view.backgroundColor = .black
        navigationItem.leftBarButtonItem = UIBarButtonItem(title: "取消", style: .plain, target: self, action: #selector(cancel))
        AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
            guard let self else { return }
            if granted { self.queue.async { self.prepare() } }
            else { DispatchQueue.main.async { self.error("请在系统设置中允许知域使用相机。") } }
        }
    }
    override func viewDidLayoutSubviews() { super.viewDidLayoutSubviews(); layer?.frame = view.bounds }
    override func viewWillDisappear(_ animated: Bool) { super.viewWillDisappear(animated); finished = true; queue.async { self.capture.stopRunning() } }
    @objc private func cancel() { finished = true; dismiss(animated: true) }
    private func prepare() {
        guard DispatchQueue.main.sync(execute: { !self.finished }) else { return }
        guard let device = AVCaptureDevice.default(for: .video), let input = try? AVCaptureDeviceInput(device: device), capture.canAddInput(input) else { DispatchQueue.main.async { self.error("无法打开相机。") }; return }
        capture.addInput(input)
        let output = AVCaptureMetadataOutput()
        guard capture.canAddOutput(output) else { return }
        capture.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        output.metadataObjectTypes = [.qr]
        DispatchQueue.main.async {
            let layer = AVCaptureVideoPreviewLayer(session: self.capture)
            layer.videoGravity = .resizeAspectFill
            layer.frame = self.view.bounds
            self.view.layer.insertSublayer(layer, at: 0)
            self.layer = layer
            let label = UILabel(); label.text = "将二维码放入画面"; label.textColor = .white; label.textAlignment = .center; label.translatesAutoresizingMaskIntoConstraints = false; self.view.addSubview(label)
            NSLayoutConstraint.activate([label.centerXAnchor.constraint(equalTo: self.view.centerXAnchor), label.bottomAnchor.constraint(equalTo: self.view.safeAreaLayoutGuide.bottomAnchor, constant: -32)])
        }
        if DispatchQueue.main.sync(execute: { !self.finished }) { capture.startRunning() }
    }
    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput objects: [AVMetadataObject], from connection: AVCaptureConnection) {
        guard !finished, let code = (objects.first as? AVMetadataMachineReadableCodeObject)?.stringValue else { return }
        finished = true
        dismiss(animated: true) { self.onCode?(code) }
    }
    private func error(_ text: String) {
        let alert = UIAlertController(title: "无法扫描", message: text, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "关闭", style: .default) { _ in self.dismiss(animated: true) })
        present(alert, animated: true)
    }
}
