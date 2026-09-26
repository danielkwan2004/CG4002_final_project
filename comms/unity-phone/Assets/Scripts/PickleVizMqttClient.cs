using System;
using System.Collections.Concurrent;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.UI;
using MQTTnet;
using MQTTnet.Client;
using MQTTnet.Protocol;
using TMPro;

public class PickleVizMqttClient : MonoBehaviour
{
    [Header("Broker settings")]
    public string brokerHost = "";
    public int brokerPort = 8883;
    private string mqttUsername = "";
    private string mqttPassword = "";

    [Header("Diagnostics")]
    public bool runTcpProbe = true;

    [Header("Topics")]
    public string sensorTopic = "fb/sensor/raw";
    public string resultTopic = "ultra96/ai/results";

    private IMqttClient mqttClient;
    public TMP_Text aiResultText;
    public TMP_Text sensorText;
    public TMP_Text statsText;
    public TMP_Text statusText;

    private readonly ConcurrentQueue<string> pendingMessages =
        new ConcurrentQueue<string>();

    private int sensorPacketCount = 0;
    private int aiResultCount = 0;
    private string latestSensorPayload = "";
    private string latestAIResultSummary = "";

    // Only display useful fields. JsonUtility ignores session IDs and the
    // potentially long sensor_seqs array without including them in the UI.
    [Serializable]
    private class AIResultDisplayPacket
    {
        public long result_seq;
        public string stroke;
        public float confidence;
        public int sample_pairs;
    }
    private float lastAIResultTime;
    private volatile bool mqttConnected = false;
    private volatile string connectionStatus = "Starting MQTT...";
    private volatile string connectionStage = "startup";
    private volatile string tlsFailure;
    private volatile bool connecting;
    private X509Certificate2 caCertificate;
    private CancellationTokenSource connectionLifetime;
    private Task connectionTask = Task.CompletedTask;
    private bool stopping;
    private bool changingAddress;
    private const string BrokerHostKey = "PickleViz.BrokerHost";
    private const string UsernameKey = "PickleViz.Username";
    [SerializeField] private TMP_InputField usernameInput;
    [SerializeField] private TMP_InputField passwordInput;
    [SerializeField] private TMP_InputField brokerInput;
    [SerializeField] private Button connectButton;
    [SerializeField] private TMP_Text addressHint;

    private long mqttBytes;
    private float statsStarted;
    private float mqttKbps;

    private void Start()
    {
        statsStarted = Time.realtimeSinceStartup;
        brokerHost = PlayerPrefs.GetString(BrokerHostKey, brokerHost);
        mqttUsername = PlayerPrefs.GetString(UsernameKey, "");
        if (brokerInput == null || usernameInput == null || passwordInput == null ||
            connectButton == null || addressHint == null)
        {
            connectionStatus = "Login UI references are missing. Assign them on MqttManager.";
            Debug.LogError(connectionStatus, this);
            return;
        }
        brokerInput.text = brokerHost;
        brokerInput.keyboardType = TouchScreenKeyboardType.URL;
        brokerInput.characterLimit = 253;
        usernameInput.text = mqttUsername;
        passwordInput.contentType = TMP_InputField.ContentType.Password;
        passwordInput.text = "";
        addressHint.text = $"TLS port {brokerPort} - enter your login details";
        connectButton.onClick.AddListener(ApplyBrokerAddress);
        connectionStatus = "Enter MQTT login details and click Connect.";
    }

    private void StartConnectionLoop()
    {
        connectionLifetime = new CancellationTokenSource();
        connectionTask = RunConnectionLoopAsync(connectionLifetime.Token);
    }

    private async void ApplyBrokerAddress()
    {
        if (changingAddress || stopping) return;
        string host = brokerInput.text.Trim();
        if (string.IsNullOrEmpty(host) || Uri.CheckHostName(host) == UriHostNameType.Unknown)
        {
            addressHint.text = "Enter an IP address or hostname, without a port or http://.";
            return;
        }

        string username = usernameInput.text.Trim();
        string password = passwordInput.text; // Preserve spaces in passwords.
        if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(password))
        {
            addressHint.text = "Enter your MQTT username and password.";
            return;
        }

        changingAddress = true;
        connectButton.interactable = false;
        brokerInput.interactable = false;
        usernameInput.interactable = passwordInput.interactable = false;
        addressHint.text = "Switching broker...";
        try
        {
            // Wait for the old loop and its callbacks to finish before changing shared state.
            connectionLifetime?.Cancel();
            await connectionTask;
            if (stopping) return;
            brokerHost = host;
            mqttUsername = username;
            mqttPassword = password;
            PlayerPrefs.SetString(UsernameKey, username);
            PlayerPrefs.SetString(BrokerHostKey, host);
            PlayerPrefs.Save();
            brokerInput.text = host;
            addressHint.text = $"Last saved broker: \n{host}:{brokerPort}";
            StartConnectionLoop();
        }
        catch (Exception exception)
        {
            if (!stopping) addressHint.text = $"Could not change broker: {exception.Message}";
            Debug.LogException(exception);
        }
        finally
        {
            changingAddress = false;
            if (!stopping)
            {
                connectButton.interactable = true;
                brokerInput.interactable = true;
                usernameInput.interactable = passwordInput.interactable = true;
            }
        }
    }

    private async Task RunConnectionLoopAsync(CancellationToken cancellationToken)
    {
        int retrySeconds = 2;
        try
        {
            while (true)
            {
                cancellationToken.ThrowIfCancellationRequested();
                bool subscribed = await ConnectAsync(cancellationToken);
                if (subscribed)
                {
                    retrySeconds = 2;
                    while (mqttClient.IsConnected)
                        await Task.Delay(500, cancellationToken);
                }

                cancellationToken.ThrowIfCancellationRequested();
                string failure = connectionStatus;
                ReleaseConnection();
                for (int remaining = retrySeconds; remaining > 0; remaining--)
                {
                    connectionStatus = $"{failure}\nRetrying in {remaining}s...";
                    await Task.Delay(1000, cancellationToken);
                }
                retrySeconds = Math.Min(retrySeconds * 2, 30);
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // Scene destruction or application shutdown intentionally stops retries.
        }
        catch (Exception exception)
        {
            connectionStatus = $"MQTT reconnect loop stopped: {exception.Message}";
            Debug.LogException(exception);
        }
        finally
        {
            ReleaseConnection();
            connectionLifetime.Dispose();
            connectionLifetime = null;
        }
    }

    private void ReleaseConnection()
    {
        if (mqttClient != null)
        {
            mqttClient.ConnectedAsync -= OnConnected;
            mqttClient.DisconnectedAsync -= OnDisconnected;
            mqttClient.ApplicationMessageReceivedAsync -= OnMessageReceived;
            mqttClient.Dispose();
            mqttClient = null;
        }
        caCertificate?.Dispose();
        caCertificate = null;
        mqttConnected = false;
    }

    private void SetConnectionStage(string stage)
    {
        connectionStage = stage;
        connectionStatus = stage;
        Debug.Log($"MQTT: {stage}");
    }

    private async Task<bool> ConnectAsync(CancellationToken cancellationToken)
    {
        connecting = true;
        tlsFailure = null;
        try
        {
            SetConnectionStage("Loading CA resource...");
            // Unity strips only the final .txt extension from ca.crt.txt.
            TextAsset caAsset = Resources.Load<TextAsset>("ca.crt");
            if (caAsset == null)
                throw new InvalidOperationException(
                    "Missing Assets/Resources/ca.crt.txt");

            SetConnectionStage("Parsing CA certificate...");
            // Decode PEM explicitly rather than relying on platform-specific import support.
            const string begin = "-----BEGIN CERTIFICATE-----";
            const string end = "-----END CERTIFICATE-----";
            string pem = caAsset.text;
            int start = pem.IndexOf(begin, StringComparison.Ordinal);
            int finish = pem.IndexOf(end, StringComparison.Ordinal);
            if (start < 0 || finish <= start)
                throw new InvalidOperationException("CA resource must contain a PEM certificate");
            start += begin.Length;
            caCertificate = new X509Certificate2(
                Convert.FromBase64String(pem.Substring(start, finish - start)));
            Debug.Log($"MQTT CA: {caCertificate.Subject}; " +
                $"valid {caCertificate.NotBefore:u} to {caCertificate.NotAfter:u}; " +
                $"device UTC {DateTime.UtcNow:u}");

            SetConnectionStage("Creating MQTT client and TLS options...");
            mqttClient = new MqttFactory().CreateMqttClient();
            mqttClient.ConnectedAsync += OnConnected;
            mqttClient.DisconnectedAsync += OnDisconnected;
            mqttClient.ApplicationMessageReceivedAsync += OnMessageReceived;

            var tlsOptions = new MqttClientTlsOptionsBuilder()
                .UseTls()
                .WithSslProtocols(SslProtocols.Tls12)
                .WithCertificateValidationHandler(context =>
                {
                    SetConnectionStage("Validating broker TLS certificate...");
                    try
                    {
                        // Chain trust is handled below; hostname and missing-cert errors are fatal.
                        if (context.Certificate == null ||
                            (context.SslPolicyErrors & ~SslPolicyErrors.RemoteCertificateChainErrors) != 0)
                            throw new AuthenticationException(
                                $"Broker certificate error: {context.SslPolicyErrors}");

                        using (var serverCertificate = new X509Certificate2(context.Certificate))
                        using (var chain = new X509Chain())
                        {
                            chain.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck;
                            chain.ChainPolicy.VerificationFlags =
                                X509VerificationFlags.AllowUnknownCertificateAuthority;
                            chain.ChainPolicy.ExtraStore.Add(caCertificate);
                            bool valid = chain.Build(serverCertificate);
                            string errors = string.Join(", ", Array.ConvertAll(chain.ChainStatus,
                                status => $"{status.Status}: {status.StatusInformation.Trim()}"));
                            int count = chain.ChainElements.Count;
                            // ExtraStore alone does not require this CA to be the trust anchor.
                            bool trustedRoot = count > 0 && string.Equals(
                                chain.ChainElements[count - 1].Certificate.Thumbprint,
                                caCertificate.Thumbprint, StringComparison.OrdinalIgnoreCase);
                            if (!valid || !trustedRoot)
                                throw new AuthenticationException(
                                    $"Broker chain rejected (bundled CA match={trustedRoot}): {errors}");
                        }
                        SetConnectionStage("TLS certificate accepted; waiting for MQTT CONNACK...");
                        return true;
                    }
                    catch (Exception exception)
                    {
                        tlsFailure = exception.GetBaseException().Message;
                        Debug.LogError($"MQTT TLS validation failed: {exception}");
                        return false;
                    }
                })
                .Build();

            var options = new MqttClientOptionsBuilder()
                .WithClientId("phone")
                .WithTcpServer(brokerHost, brokerPort)
                .WithCredentials(mqttUsername, mqttPassword)
                .WithTimeout(TimeSpan.FromSeconds(15))
                .WithKeepAlivePeriod(TimeSpan.FromSeconds(10))
                .WithTlsOptions(tlsOptions)
                .Build();

            if (runTcpProbe)
                await ProbeTcpAsync(cancellationToken);

            SetConnectionStage($"Connecting TCP/TLS to {brokerHost}:{brokerPort} (15s timeout)...");
            var result = await mqttClient.ConnectAsync(options, cancellationToken);
            Debug.Log($"MQTT connect result: {result.ResultCode}");
            if (!mqttClient.IsConnected)
                throw new InvalidOperationException($"Broker rejected connection: {result.ResultCode}");
            return true;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception exception)
        {
            mqttConnected = mqttClient != null && mqttClient.IsConnected;
            connectionStatus = $"MQTT failed during {connectionStage}\n" +
                (tlsFailure ?? exception.GetBaseException().Message);
            Debug.LogError($"{connectionStatus}\n{exception}");
            return false;
        }
        finally
        {
            connecting = false;
        }
    }

    private async Task ProbeTcpAsync(CancellationToken cancellationToken)
    {
        SetConnectionStage($"Testing TCP to {brokerHost}:{brokerPort} (10s timeout)...");
        // This temporary connection sends no MQTT or TLS data. The broker may log EOF.
        using (var probe = new TcpClient())
        {
            Task connectTask = probe.ConnectAsync(brokerHost, brokerPort);
            Task completed = await Task.WhenAny(connectTask, Task.Delay(TimeSpan.FromSeconds(10), cancellationToken));
            if (completed != connectTask)
            {
                probe.Close();
                ObserveProbeCompletionAsync(connectTask);
                cancellationToken.ThrowIfCancellationRequested();
                throw new TimeoutException(
                    $"TCP probe timed out: Android cannot establish TCP to {brokerHost}:{brokerPort}. " +
                    "TLS and MQTT authentication have not started.");
            }

            await connectTask;
            Debug.Log($"MQTT TCP probe succeeded: {probe.Client.LocalEndPoint} -> " +
                $"{probe.Client.RemoteEndPoint}. Starting a separate MQTT/TLS connection next.");
        }
    }

    private static async void ObserveProbeCompletionAsync(Task connectTask)
    {
        // Closing a pending socket can complete its task with an exception later.
        try { await connectTask; }
        catch (Exception) { /* The timeout is already reported by ProbeTcpAsync. */ }
    }

    private async Task OnConnected(
        MqttClientConnectedEventArgs args
    )
    {
        mqttConnected = true;
        SetConnectionStage("MQTT connected; subscribing...");
        Debug.Log("Connected to MQTT broker");


        if (!mqttClient.IsConnected)
        {
            Debug.LogError("MQTT client is not connected after connection attempt.");
            return;
        }

        await mqttClient.SubscribeAsync(
            new MqttTopicFilterBuilder()
                .WithTopic(sensorTopic)
                .WithQualityOfServiceLevel(
                    MqttQualityOfServiceLevel.AtMostOnce
                )
                .Build()
        );

        await mqttClient.SubscribeAsync(
            new MqttTopicFilterBuilder()
                .WithTopic(resultTopic)
                .WithQualityOfServiceLevel(
                    MqttQualityOfServiceLevel.AtLeastOnce
                )
                .Build()
        );

        SetConnectionStage("MQTT Subscribed");
        Debug.Log("Subscribed to MQTT topics");
    }

    private Task OnDisconnected(
        MqttClientDisconnectedEventArgs args
    )
    {
        mqttConnected = false;
        string detail = args.Exception != null
            ? args.Exception.GetBaseException().Message
            : args.Reason.ToString();
        // ConnectAsync owns the failure status while connecting; do not hide its diagnostics.
        if (!connecting)
            connectionStatus = $"MQTT Disconnected: {detail}";
        Debug.LogWarning($"MQTT disconnected: {detail}\n{args.Exception}");
        return Task.CompletedTask;
    }

    private Task OnMessageReceived(
        MqttApplicationMessageReceivedEventArgs args
    )
    {
        string topic = args.ApplicationMessage.Topic;
        string payload = Encoding.UTF8.GetString(
            args.ApplicationMessage.PayloadSegment
        );

        pendingMessages.Enqueue(
            topic + "\n" + payload
        );
        mqttBytes += Encoding.UTF8.GetByteCount(payload);

        if (topic == resultTopic)
            Debug.Log($"Received AI result [{topic}] ({args.ApplicationMessage.PayloadSegment.Count} bytes)");
        else
            Debug.Log($"Received [{topic}]: {payload}");
        return Task.CompletedTask;
    }

    private void Update()
    {
        while (pendingMessages.TryDequeue(out string message))
        {
            int separator = message.IndexOf('\n');

            string topic = message.Substring(0, separator);
            string payload = message.Substring(separator + 1);

            if (topic == sensorTopic)
            {
                sensorPacketCount++;
                latestSensorPayload = payload;
            }
            else if (topic == resultTopic)
            {
                aiResultCount++;
                latestAIResultSummary = BuildAIResultSummary(payload);
                lastAIResultTime = Time.realtimeSinceStartup;
            }
        }

        float elapsed = Time.realtimeSinceStartup - statsStarted;
        if (elapsed >= 5f)
        {
            mqttKbps = (float)(mqttBytes * 8.0 / elapsed / 1000.0);
            mqttBytes = 0;
            statsStarted = Time.realtimeSinceStartup;
        }

        if(statusText)
        {
            statusText.text = connectionStatus;
        }

        if (sensorText)
        {
            sensorText.text =
                $"Sensor packet: " + latestSensorPayload;
        }

        if (aiResultText)
        {
            // Display stroke names as plain text, even if they contain markup.
            aiResultText.richText = false;
            aiResultText.text = aiResultCount == 0
                ? "AI results: waiting for packets..."
                : latestAIResultSummary + "\n" +
                  $"Last packet: {Time.realtimeSinceStartup - lastAIResultTime:F1}s ago";
        }

        if (statsText)
        {
            statsText.text =
                $"Sensor packets: {sensorPacketCount}\n" +
                $"AI results: {aiResultCount}\n" +
                $"\nMQTT receive: {mqttKbps:F2} kbps";
        }
    }

    private static string BuildAIResultSummary(string payload)
    {
        try
        {
            var result = JsonUtility.FromJson<AIResultDisplayPacket>(payload);
            if (result == null || string.IsNullOrWhiteSpace(result.stroke) ||
                float.IsNaN(result.confidence) ||
                float.IsInfinity(result.confidence) ||
                result.confidence < 0f || result.confidence > 1f)
                return "AI result received: missing or invalid summary fields";

            string stroke = result.stroke.Replace('\r', ' ').Replace('\n', ' ').Replace('\t', ' ');
            if (stroke.Length > 60) stroke = stroke.Substring(0, 60) + "...";
            return $"AI result #{result.result_seq}\n" +
                   $"Stroke: {stroke} | Confidence: {result.confidence * 100f:F0}%\n" +
                   $"Sample pairs: {result.sample_pairs}";
        }
        catch (ArgumentException)
        {
            // A malformed packet must not break the Unity Update loop.
            return "AI result received: invalid JSON";
        }
    }

    private void OnApplicationQuit()
    {
        stopping = true;
        connectionLifetime?.Cancel();
    }

    private void OnDestroy()
    {
        stopping = true;
        if (connectButton != null) connectButton.onClick.RemoveListener(ApplyBrokerAddress);
        connectionLifetime?.Cancel();
    }
}
