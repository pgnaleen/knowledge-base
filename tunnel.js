const localtunnel = require('localtunnel');
const fs = require('fs');

const BACKEND_PORT = 8001;

(async () => {
    console.log(`Starting tunnel for sg-property-agent backend (port ${BACKEND_PORT})...`);

    try {
        const tunnel = await localtunnel({ port: BACKEND_PORT });

        const publicUrl = tunnel.url;
        const webhookUrl = `${publicUrl}/webhook/whatsapp`;

        console.log('');
        console.log('='.repeat(60));
        console.log(`Public URL    : ${publicUrl}`);
        console.log(`WhatsApp Hook : ${webhookUrl}`);
        console.log('='.repeat(60));
        console.log('');
        console.log('Paste the WhatsApp Hook URL into Meta App Dashboard:');
        console.log('  App Dashboard -> WhatsApp -> Configuration -> Webhook URL');
        console.log(`  Verify Token  : check backend/.env -> WHATSAPP_VERIFY_TOKEN`);
        console.log('');
        console.log('Press Ctrl+C to stop the tunnel.');

        fs.writeFileSync(
            'tunnel-url.txt',
            `Public URL   : ${publicUrl}\nWhatsApp Hook: ${webhookUrl}\n`
        );

        tunnel.on('close', () => {
            console.log('Tunnel closed.');
        });

        process.on('SIGINT', () => {
            console.log('\nShutting down tunnel...');
            tunnel.close();
            process.exit(0);
        });

    } catch (err) {
        console.error('Failed to start tunnel:', err.message);
        process.exit(1);
    }
})();
