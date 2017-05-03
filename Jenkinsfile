#!groovy
timestamps {
    node {
        try {
            checkout scm
            docker.withRegistry('https://5gex.tmit.bme.hu') {
                def image = docker.build("tnova-connector:1.0.0.${env.BUILD_NUMBER}")
                image.push('unstable')
            }
			currentBuild.result = 'SUCCESS'
        } catch (any) {
			currentBuild.result = 'FAILURE'
			throw any
		} finally {
			step([$class: 'Mailer', recipients: '5gex-devel@tmit.bme.hu'])
		}
    }
}
